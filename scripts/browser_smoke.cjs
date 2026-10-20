// Optional browser smoke. Install playwright outside the repository, expose it with NODE_PATH.
const { chromium } = require('playwright');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  try {
    await page.goto(process.env.STUDIO_URL || 'http://127.0.0.1:8002/');
    await page.locator('#mode').filter({hasText:'模拟模式'}).waitFor();
    const identity='browser-smoke-'+Date.now();
    await page.locator('#identity').fill(identity);
    await page.locator('#identity').dispatchEvent('change');
    await page.locator('#prompt').fill('轻便运动鞋，售价 99，蓝色简洁风格');
    await page.locator('#submit').click();
    await page.locator('#state').filter({hasText:'WAITING_APPROVAL'}).waitFor({timeout:30000});
    await page.locator('.card').nth(2).waitFor();
    await page.locator('.card img').first().evaluate(image=>image.complete && image.naturalWidth>0 || new Promise(resolve=>image.onload=resolve));
    const first=page.locator('.card').first();
    await first.locator('input').fill('79');
    await first.getByRole('button',{name:'保存价格'}).click();
    await page.locator('.card').nth(3).waitFor();
    if(await page.locator('.card').first().locator('input').inputValue()!=='79')throw Error('Price edit not reflected');
    fs.mkdirSync('data',{recursive:true});
    await page.screenshot({path:'data/studio.png',fullPage:true});
    await page.locator('.card').first().getByRole('button',{name:'确认此版本'}).click();
    await page.locator('#state').filter({hasText:'SUCCESS'}).waitFor({timeout:30000});
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'下载 PNG'}).click();
    const download=await pending;
    await download.saveAs('data/browser-export.png');
    if(fs.readFileSync('data/browser-export.png').subarray(1,4).toString()!=='PNG')throw Error('Invalid PNG');
    if(errors.length)throw Error(errors.join('\n'));
    await page.reload();
    await page.locator('#identity').fill(identity);
    await page.locator('#identity').dispatchEvent('change');
    await page.locator('.task').first().waitFor();
    console.log('PASS: browser submit -> 3 previews -> price edit -> approval -> PNG download; no JavaScript errors');
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
