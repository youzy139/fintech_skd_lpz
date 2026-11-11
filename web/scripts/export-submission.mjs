import { chromium } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../../', import.meta.url))
const source = path.join(root, 'docs/submission/product-technical-design.md')
const output = path.join(root, 'server/data/release')
const escape = text => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const inline = text => escape(text).replaceAll(String.fromCharCode(96), '').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

function section(markdown) {
  const lines = markdown.trim().split(/\r?\n/)
  const parts = []
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index]
    if (!line.trim()) continue
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) { parts.push('<h' + heading[1].length + '>' + inline(heading[2]) + '</h' + heading[1].length + '>'); continue }
    if (line.startsWith('|')) {
      const rows = []
      while (index < lines.length && lines[index].startsWith('|')) {
        const cells = lines[index].split('|').slice(1, -1).map(cell => cell.trim())
        if (!cells.every(cell => /^:?-+:?$/.test(cell))) rows.push(cells)
        index++
      }
      index--
      parts.push('<table>' + rows.map((row, position) => '<tr>' + row.map(cell => '<' + (position ? 'td' : 'th') + '>' + inline(cell) + '</' + (position ? 'td' : 'th') + '>').join('') + '</tr>').join('') + '</table>')
      continue
    }
    if (/^\d+\. /.test(line)) {
      const items = []
      while (index < lines.length && /^\d+\. /.test(lines[index])) items.push('<li>' + inline(lines[index++].replace(/^\d+\. /, '')) + '</li>')
      index--
      parts.push('<ol>' + items.join('') + '</ol>')
      continue
    }
    parts.push('<p>' + inline(line) + '</p>')
  }
  return '<section>' + parts.join('\n') + '</section>'
}

const markdown = await readFile(source, 'utf8')
const style = '@page{size:A4;margin:18mm 17mm 19mm}*{box-sizing:border-box}body{color:#253b38;font-family:Microsoft YaHei,Noto Sans CJK SC,sans-serif;font-size:10.5pt;line-height:1.7;margin:0}section{break-after:page}section:last-child{break-after:auto}h1{font-size:30pt;padding-top:32mm;margin-bottom:18mm}h2{color:#23745f;font-size:20pt;margin:5mm 0 8mm;border-bottom:2px solid #23745f;padding-bottom:4mm}p{margin:0 0 4mm}table{border-collapse:collapse;width:100%;margin:6mm 0;font-size:9pt}th{background:#e9f0e9;color:#25483e;text-align:left}th,td{border-bottom:1px solid #cddbd2;padding:3mm;vertical-align:top}tr{break-inside:avoid}li{margin-bottom:3mm}'
const html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MarketLens 产品与技术方案 · 准备稿</title><style>' + style + '</style><body>' + markdown.split(/\r?\n---\r?\n/).map(section).join('\n') + '</body></html>'
await mkdir(output, { recursive: true })
const htmlPath = path.join(output, 'MarketLens-product-technical-draft.html')
const pdfPath = path.join(output, 'MarketLens-product-technical-draft.pdf')
await writeFile(htmlPath, html, 'utf8')
const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || (process.env.CI ? undefined : 'chrome'), headless: true })
try {
  const page = await browser.newPage()
  await page.goto(pathToFileURL(htmlPath).href)
  await page.evaluate(() => document.fonts.ready)
  await page.pdf({ path: pdfPath, format: 'A4', printBackground: true, displayHeaderFooter: true, headerTemplate: '<div></div>', footerTemplate: '<div style="font-size:8px;width:100%;padding:0 17mm;color:#73817b;display:flex;justify-content:space-between"><span>MarketLens · 2026-11-11 · 送审准备稿 / 非正式发布</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>', preferCSSPageSize: true })
  console.log(JSON.stringify({ pdf: pdfPath, sections: markdown.split(/\r?\n---\r?\n/).length, status: 'draft' }))
} finally { await browser.close() }
