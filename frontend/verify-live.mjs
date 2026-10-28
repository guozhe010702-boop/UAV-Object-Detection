// Real board/browser acceptance. Never stores the device code in reports or screenshots.
import {chromium} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'.cache','live-browser');mkdirSync(output,{recursive:true});
const adb=process.env.UAV_ADB||path.resolve(root,'../../Tools/RKDevTool_296/unpacked/RKDevTool_Release_v2.96/bin/adb.exe');
const token=execFileSync(adb,['shell','cat /userdata/uav-object-detection/data/admin-token.txt'],{encoding:'utf8'}).trim();
const address=process.env.UAV_URL||'http://192.168.2.221:8088';
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
try{
 const context=await browser.newContext({viewport:{width:1440,height:1080}});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(address);await page.getByLabel('设备访问码').fill(token);
 await page.getByRole('button',{name:'进入工作台'}).click();await page.getByRole('heading',{name:'实时检测',exact:true}).waitFor();
 async function api(path,body,method){const r=await context.request.fetch(address+'/api/'+path,{method:method||(body?'POST':'GET'),data:body});if(!r.ok())throw new Error(path+': '+await r.text());return r.json()}
 const initial=await api('status');
 if(initial.state==='completed'){
  await page.getByAltText('NPU 实时检测结果').waitFor({state:'visible'});
  await page.screenshot({path:path.join(output,'aerial-detection.png'),fullPage:true});
 }
 await api('inference/stop',{});
 let settings=await api('settings');settings={...settings,source_kind:'imx415',source_uri:'/dev/video44',autostart_inference:false};
 await api('settings',settings,'PUT');await page.reload();await page.getByRole('button',{name:'开始检测',exact:true}).click();
 let first;for(let i=0;i<100;i++){first=await api('status');if(first.state==='running')break;if(first.error)throw new Error(first.error);await page.waitForTimeout(150)}
 if(first.state!=='running')throw new Error('Real camera did not start');
 await page.getByAltText('NPU 实时检测结果').waitFor({state:'visible'});
 const samples=[];for(let i=0;i<25;i++){await page.waitForTimeout(1000);const s=await api('status');
  if(s.error||s.stale||!s.inference_connected)throw new Error('Real stream unhealthy: '+JSON.stringify(s));
  samples.push({at:s.updated_at,fps:s.processing_fps,inference_ms:s.inference_ms,capture_fps:s.capture_fps,
   processed:s.frames_processed,dropped:s.frames_dropped,cpu:s.resources.cpu_percent,memory:s.resources.memory_percent,npu:s.resources.npu_percent});
 }
 const current=await api('status');if(current.frame_id<=first.frame_id)throw new Error('Frames did not advance');
 if(current.npu?.core_mask!==7||!current.resources.npu_percent)throw new Error('NPU telemetry missing');
 const refused=await context.request.put(address+'/api/settings',{data:{...settings,confidence:.5}});
 if(refused.status()!==409)throw new Error('Running settings protection failed');
 await page.screenshot({path:path.join(output,'camera-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'camera-mobile.png'),fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw new Error('Live mobile overflow');
 await page.setViewportSize({width:1440,height:1080});
 await page.getByRole('button',{name:'检测记录',exact:true}).click();
 await page.waitForTimeout(600);const records=await api('records');if(!records.total)throw new Error('No actual records');
 const snapshot=await context.request.get(address+'/api/records/'+records.items[0].id+'/snapshot');if(!snapshot.ok()||(await snapshot.body()).length<1000)throw new Error('Snapshot unavailable');
 await page.screenshot({path:path.join(output,'records-desktop.png'),fullPage:true});
 const csv=await context.request.get(address+'/api/records.csv');if(!csv.ok()||!(await csv.text()).includes('UTC'))throw new Error('CSV unavailable');
 await page.getByRole('button',{name:'实时检测',exact:true}).click();
 await page.getByRole('button',{name:'停止检测',exact:true}).click();await page.waitForTimeout(500);
 const stopped=await api('status');if(stopped.worker_pid||stopped.state!=='stopped')throw new Error('Stop left a worker');
 await page.getByRole('button',{name:'开始检测',exact:true}).click();await page.waitForTimeout(2000);
 if(!(await api('status')).inference_connected)throw new Error('Restart failed');
 if(errors.length)throw new Error(errors.join('\n'));
 writeFileSync(path.join(output,'result.json'),JSON.stringify({address,initial_image:initial.objects,realCamera:true,
  npuCoreMask:7,frameMatchedJpeg:true,records:records.total,snapshot:true,csv:true,settingsProtected:true,
  stopAndRestart:true,mobileNoOverflow:true,samples,pageErrors:errors},null,2));
 console.log('Real board browser acceptance passed: NPU, camera, JPEG, records, CSV, mobile, stop/restart.');
}finally{await browser.close()}
