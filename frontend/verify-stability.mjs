// Real browser + board status. No simulated counters, and no controls/restarts during the run.
import {chromium} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdirSync,writeFileSync,appendFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'.cache','stability-browser-'+new Date().toISOString().replace(/[:.]/g,'-'));
mkdirSync(output,{recursive:true});
const adb=process.env.UAV_ADB||path.resolve(root,'../../Tools/RKDevTool_296/unpacked/RKDevTool_Release_v2.96/bin/adb.exe');
const token=execFileSync(adb,['shell','cat /userdata/uav-object-detection/data/admin-token.txt'],{encoding:'utf8'}).trim();
const address=process.env.UAV_URL||'http://192.168.2.221:8088';
const seconds=Number(process.env.UAV_TEST_SECONDS||1800);
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const errors=[],samples=[];let runId;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1080}});
 const page=await context.newPage();page.on('pageerror',e=>errors.push({at:Date.now(),error:e.message}));
 await page.goto(address);await page.getByLabel('设备访问码').fill(token);
 await page.getByRole('button',{name:'进入工作台'}).click();
 const image=page.getByAltText('NPU 实时检测结果');await image.waitFor({state:'visible'});
 await image.scrollIntoViewIfNeeded();
 const cdp=await context.newCDPSession(page);await cdp.send('Performance.enable');
 const status=async()=>{const r=await context.request.get(address+'/api/status',{timeout:6000});try{return await r.json()}finally{await r.dispose()}};
 const initial=await status();runId=initial.run_id;
 const start=performance.now();const deadline=start+seconds*1000;
 const csv=path.join(output,'samples.csv');writeFileSync(csv,'elapsed_s,processed,processing_fps,preview_update_fps,preview_mbps,js_heap_bytes,dom_nodes,frame_id\n');
 let next=start;
 while(performance.now()<deadline){
  try{
   const s=await status();if(s.run_id!==runId||!s.inference_connected)throw new Error('Stream changed or became unhealthy');
   const display=await image.evaluate(el=>({fps:Number(el.dataset.uniqueFrameFps||0),mbps:Number(el.dataset.previewMbps||0),id:el.dataset.frameId||''}));
   const perf=Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(x=>[x.name,x.value]));
   const row={elapsed:(performance.now()-start)/1000,processed:s.frames_processed,processingFps:s.processing_fps,
     previewFps:display.fps,previewMbps:display.mbps,heap:perf.JSHeapUsedSize,nodes:perf.Nodes,frameId:display.id};
   samples.push(row);appendFileSync(csv,[row.elapsed,row.processed,row.processingFps,row.previewFps,row.previewMbps,row.heap,row.nodes,row.frameId].join(',')+'\n');
   if(samples.length===1||samples.length%300===0)await page.screenshot({path:path.join(output,'preview-'+samples.length+'.png')});
  }catch(e){errors.push({at:Date.now(),error:e.message})}
  next+=1000;const delay=Math.min(next,deadline)-performance.now();if(delay>0)await new Promise(r=>setTimeout(r,delay));
 }
 const mean=key=>samples.slice(5).reduce((a,x)=>a+(x[key]||0),0)/Math.max(1,samples.length-5);
 const result={seconds,elapsedSeconds:(performance.now()-start)/1000,runId,samples:samples.length,
  meanProcessingFps:mean('processingFps'),meanPreviewUniqueFrameFps:mean('previewFps'),meanPreviewMbps:mean('previewMbps'),
  firstHeap:samples[5]?.heap,lastHeap:samples.at(-1)?.heap,errors,
  passed:errors.length===0&&samples.length>=seconds*.99&&mean('previewFps')>=25,
  scope:'Headless real Chromium image-load updates from distinct server frame IDs, not measured physical-display paint or camera-to-screen latency'};
 writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify({output,...result}));
}finally{await browser.close()}
