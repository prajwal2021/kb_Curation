import { chromium } from 'playwright';
import fs from 'fs';
const B='http://localhost:3010', out='public';
fs.mkdirSync(out,{recursive:true});
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport:{width:1600,height:900}, deviceScaleFactor:2, storageState:process.env.STATE || 'build/state.json' });
const page = await ctx.newPage();
const boxes = {};
const go = async p => { await page.goto(B+p); await page.waitForLoadState('networkidle').catch(()=>{}); await page.waitForTimeout(1500); };
const box = async (name, loc) => { const b = await loc.first().boundingBox(); boxes[name]=b; if(!b) console.log('NO BOX', name); };
const shot = async n => { await page.mouse.move(-10,-10); await page.waitForTimeout(300); await page.screenshot({path:`${out}/${n}.png`}); console.log('shot', n); };

// import: knowledge base
await go('/k12/servicenow/kb');
await box('kb.tabs', page.locator('text=Published').locator('xpath=ancestor::div[1]'));
await box('kb.internal', page.getByText('Internal only', {exact:true}).nth(0));
await box('kb.tree', page.getByPlaceholder('Filter categories').locator('xpath=ancestor::div[2]'));
await shot('kb');
// web pages
await go('/k12/servicenow/web-pages');
await box('wp.ok', page.getByText('checked in the last 24 hours', {exact:false}));
await box('wp.row', page.getByText('Texas Tech K-12 Student Handbook').locator('xpath=ancestor::div[3]'));
await box('wp.chips', page.getByText('Blackboard Learn › Assignments').locator('xpath=ancestor::div[1]'));
await shot('webpages');
// to do
await go('/k12/servicenow');
const row = page.getByText('What is the address and contact information for TTU K-12?').first();
await row.scrollIntoViewIfNeeded(); await page.waitForTimeout(500);
await box('todo.row', row.locator('xpath=ancestor::a[1]'));
await box('todo.badge', page.locator('nav, aside').getByText('To do').first());
await shot('todo');
await go('/k12/servicenow');
await shot('todo-top');
// article
await go('/k12/servicenow/article/647');
await box('art.reason', page.getByText('Why this was suggested').locator('xpath=ancestor::div[1]'));
await box('art.diff', page.locator('ins, .bg-emerald-100, [class*="emerald"]').first());
await box('art.state', page.getByText('State', {exact:true}).locator('xpath=ancestor::div[1]'));
const pub = page.getByRole('button', { name: /^Publish/ });
await box('art.publish', pub);
await box('art.sendback', page.getByRole('button', { name: /back to draft|Send back/i }));
await shot('article');
await pub.first().click(); await page.waitForTimeout(2000);
await box('art.state2', page.getByText('State', {exact:true}).locator('xpath=ancestor::div[1]'));
await shot('article-published');
// release
await go('/k12/servicenow/publish');
await box('rel.next', page.getByText('NEXT VERSION', {exact:false}).locator('xpath=ancestor::div[1]'));
const note = page.getByPlaceholder(/What is in this version/);
await note.fill('Office hours updated from the TTU K-12 Contact page');
const rb = page.getByRole('button', { name: /Release/ });
await box('rel.button', rb); await box('rel.changes', page.getByText('Office hours', {exact:false}).first());
await shot('release');
await rb.first().click(); await page.waitForTimeout(2500);
await box('rel.history', page.getByText('Version history').locator('xpath=following-sibling::*[1]'));
await shot('release-done');
// history + users
await go('/k12/history');
await box('hist.list', page.locator('main').locator('ul, ol, [class*="divide"]').first());
await shot('history');
await go('/k12/users');
await box('users.table', page.locator('main table, main ul, main [class*="divide"]').first());
await shot('users');
// how it works (for outro/intro background)
await go('/k12/servicenow/how-it-works');
await shot('how');
fs.writeFileSync('src/boxes.json', JSON.stringify(boxes,null,1));
await browser.close();
