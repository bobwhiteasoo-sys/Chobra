import {expect,test} from '@playwright/test';
for(const width of [360,768,1440]){
 test(`landing explains the product and works at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:1000});
  await page.route('**/api/v1/me',route=>route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({code:'UNAUTHENTICATED',message:'Войдите'})}));
  await page.goto('/');
  await expect(page.getByRole('heading',{level:1})).toContainText('Chobra');
  await expect(page.getByRole('link',{name:'Попробовать бесплатно',exact:true})).toHaveAttribute('href','/login');
  await expect(page.getByRole('link',{name:'Инструкция',exact:true})).toHaveAttribute('target','_blank');
  await expect(page.locator('.example-reward')).toHaveText('+10 очков');
  await page.getByRole('button',{name:'За решение',exact:true}).click();
  await expect(page.locator('.example-reward')).toHaveText('0 очков');
  await expect(page.locator('.example-verdict')).toContainText('Без решения награда не начисляется');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
  const lines=await page.locator('h1').evaluate(el=>el.getBoundingClientRect().height/parseFloat(getComputedStyle(el).lineHeight));
  expect(lines).toBeLessThanOrEqual(2.1);
 });
}
