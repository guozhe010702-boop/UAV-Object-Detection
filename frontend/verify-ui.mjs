// Real HTTP/backend/browser checks. Artifacts stay under .cache, never seed application records.
import {chromium} from '@playwright/test';
import {spawn} from 'node:child_process';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'.cache','browser-check');mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv','Scripts','python.exe');
const server=spawn(python,['-m','uav_app.cli','serve','--port','8089'],{cwd:root,
  env:{...process.env,PYTHONPATH:path.join(root,'backend'),UAV_DATA_DIR:path.join(output,'data')},stdio:['ignore','pipe','pipe']});
let logs='';server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
let browser;
try{
  let ready=false;for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:8089/api/health')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100));}
  if(!ready)throw new Error('Backend failed to start: '+logs);
  const token=readFileSync(path.join(output,'data','admin-token.txt'),'utf8').trim();
  browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1080},deviceScaleFactor:1});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8089/');await page.getByLabel('设备访问码').fill(token);
  await page.getByRole('button',{name:'进入工作台'}).click();
  await page.getByRole('heading',{name:'实时检测',exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'live-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'模型管理',exact:true}).click();
  await page.getByLabel('RKNN 模型',{exact:true}).setInputFiles(path.join(root,'artifacts/visdrone-yolo11n-fp16-640/model.rknn'));
  await page.getByLabel('配套模型清单').setInputFiles(path.join(root,'artifacts/visdrone-yolo11n-fp16-640/manifest.json'));
  await page.getByRole('button',{name:'校验并导入'}).click();
  await page.getByRole('button',{name:'设为待用模型',exact:true}).first().waitFor();
  await page.getByRole('button',{name:'设为待用模型',exact:true}).first().click();
  await page.getByRole('button',{name:'已设为待用',exact:false}).first().waitFor();
  await page.screenshot({path:path.join(output,'models-desktop.png'),fullPage:true});
  for(const name of ['检测记录','数据统计','设备设置']){
    await page.getByRole('button',{name,exact:true}).click();
    await page.getByRole('heading',{name,exact:true}).waitFor();
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw new Error('Desktop overflow: '+name);
  }
  await page.getByLabel('置信度阈值').fill('0.35');await page.getByRole('button',{name:'保存设置'}).click();
  await page.getByRole('status').waitFor();
  await page.getByRole('button',{name:'实时检测',exact:true}).click();
  await page.waitForTimeout(1200);
  if(await page.locator('input[hidden]').isVisible())throw new Error('Native file input escaped its hidden attribute');
  await page.setViewportSize({width:390,height:844});
  for(const name of ['实时检测','检测记录','数据统计','模型管理','设备设置']){
    const box=await page.getByRole('button',{name,exact:true}).boundingBox();
    if(!box || box.x<0 || box.x+box.width>391)throw new Error('Mobile navigation clipped: '+name);
  }
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw new Error('Mobile page overflow');
  await page.screenshot({path:path.join(output,'live-mobile.png'),fullPage:true});
  if(errors.length)throw new Error(errors.join('\n'));
  writeFileSync(path.join(output,'result.json'),JSON.stringify({login:true,realRknnUpload:true,manifestValidation:true,
    modelSelection:true,fivePages:true,settingsSave:true,mobileNoOverflow:true,pageErrors:errors,
    inferencePerformed:false,cameraOpened:false},null,2));
  console.log('Browser checks passed: login, real RKNN upload, model selection, five pages, settings, mobile layout.');
}finally{if(browser)await browser.close();server.kill();writeFileSync(path.join(output,'server.log'),logs);}
