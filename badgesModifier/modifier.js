'use strict'

/**
 * @file badgesModifier/modifier.js
 * @description 使用 Node.js 复刻 modifier.py 逻辑：
 *  - 从 battleAtlas.xml 读取 SubTexture 坐标
 *  - 对匹配的 badge_* 区域清空并绘制：
 *      * 若配置为 PNG 图标，则缩放至 80% 并居中粘贴
 *      * 若配置为 RGBA 颜色，则绘制居中的圆形（80% 宽高）
 *  - 输出 PNG 与 XML 到 ./output，并将 PNG 重命名为 .dds
 */

const fs = require('fs')
const path = require('path')
const { promisify } = require('util')
const xml2js = require('xml2js')
const sharp = require('sharp')

const readFile = promisify(fs.readFile)
const writeFile = promisify(fs.writeFile)

const OUTPUT_PATH = path.join(__dirname, 'output')
const ICON_BASE_PATH = path.join(__dirname, 'assets')

/**
 * @type {BadgeColors}
 */
const colors = {
    badge_10: 'bot.png',
    badge_11: [241, 0, 0, 255],
    badge_12: [0, 193, 0, 255],
    badge_13: [102, 170, 255, 255],
    badge_14: [204, 68, 255, 255],
    badge_15: [255, 215, 0, 255],
    badge_16: 'crown.png',
    badge_17: 'question.png',
}

/**
 * @param {string} xmlPath
 * @returns {Promise<Array<{name:string,x:number,y:number,width:number,height:number}>>}
 */
async function parseCoordinates(xmlPath) {
    const xml = await readFile(xmlPath, 'utf8')
    // 开启 trim/normalize，并保留数组，便于统一处理
    const parsed = await xml2js.parseStringPromise(xml, { trim: true, normalize: true })
    let sub = parsed && parsed.root && parsed.root.SubTexture ? parsed.root.SubTexture : []

    // 将可能的单对象归一为数组
    if (sub && !Array.isArray(sub)) sub = [sub]

    /**
     * 递归遍历对象树，收集所有形如：
     *  - { $: { name,x,y,width,height } }
     *  - { name, x, y, width, height }（作为子元素）
     * 的节点
     * @param {any} node
     * @param {Array<any>} acc
     */
    function collectSubTextures(node, acc) {
      if (!node) return
      if (Array.isArray(node)) {
        for (const item of node) collectSubTextures(item, acc)
        return
      }
      if (typeof node === 'object') {
        const hasAttr = node.$ && (node.$.name != null) && (node.$.x != null) && (node.$.y != null) && (node.$.width != null) && (node.$.height != null)
        const hasChild = (node.name != null) && (node.x != null) && (node.y != null) && (node.width != null) && (node.height != null)
        if (hasAttr || hasChild) acc.push(node)
        for (const key of Object.keys(node)) {
          collectSubTextures(node[key], acc)
        }
      }
    }

    // 若标准位置没有取到，则回退到全树扫描
    let nodes = []
    if (Array.isArray(sub) && sub.length > 0) {
      nodes = sub
    } else {
      collectSubTextures(parsed, nodes)
    }

    function textOf(v) {
      if (v == null) return ''
      if (Array.isArray(v)) return textOf(v[0])
      if (typeof v === 'object' && v._ != null) return String(v._).trim()
      return String(v).trim()
    }

    const list = nodes
      .filter((node) => node)
      .map((node) => {
        const src = node.$ ? node.$ : node
        return {
          name: textOf(src.name),
          x: Number(textOf(src.x)),
          y: Number(textOf(src.y)),
          width: Number(textOf(src.width)),
          height: Number(textOf(src.height)),
        }
      })

    return list.filter((it) => Object.prototype.hasOwnProperty.call(colors, it.name))
}

/**
 * 在指定矩形内清空区域
 * @param {Buffer} inputPng PNG 原图数据
 * @param {{x:number,y:number,width:number,height:number}} rect
 * @returns {Promise<Buffer>} 处理后的 PNG 数据
 */
async function clearRect(inputPng, rect) {
    // 确保底图有 alpha 通道
    const base = sharp(inputPng).ensureAlpha()
    // 使用实心（alpha=1）的覆盖图，配合 dest-out 模式实现“擦除”
    const overlay = await sharp({
        create: { width: rect.width, height: rect.height, channels: 4, background: { r: 255, g: 255, b: 255, alpha: 1 } },
    }).png().toBuffer()
    return base
        .composite([{ input: overlay, left: rect.x, top: rect.y, blend: 'dest-out' }])
        .png({ compressionLevel: 3 })
        .toBuffer()
}

/**
 * 在矩形中绘制颜色圆形
 * @param {Buffer} inputPng
 * @param {{x:number,y:number,width:number,height:number}} rect
 * @param {[number,number,number,number]} rgba
 * @returns {Promise<Buffer>}
 */
async function drawCircle(inputPng, rect, rgba) {
    const circleSize = Math.floor(Math.min(rect.width, rect.height) * 0.6)

    const svg = `<svg width="${circleSize}" height="${circleSize}"><circle cx="${circleSize / 2}" cy="${circleSize / 2}" r="${circleSize / 2}" fill="rgba(${rgba[0]},${rgba[1]},${rgba[2]},${rgba[3] / 255})"/></svg>`
    const circleBuf = Buffer.from(svg)
    const left = rect.x + Math.floor((rect.width - circleSize) / 2)
    const top = rect.y + Math.floor((rect.height - circleSize) / 2)

    return sharp(inputPng)
        .composite([{ input: circleBuf, left, top }])
        .png({ compressionLevel: 3 })
        .toBuffer()
}

/**
 * 将 PNG 图标缩放为 80% 尺寸并居中贴到矩形
 * @param {Buffer} inputPng
 * @param {{x:number,y:number,width:number,height:number}} rect
 * @param {string} iconFile
 * @returns {Promise<Buffer>}
 */
async function pasteIcon(inputPng, rect, iconFile) {
    const iconPath = path.join(ICON_BASE_PATH, iconFile)
    if (!fs.existsSync(iconPath)) {
        console.warn(`图标文件不存在: ${iconPath}`)
        return inputPng
    }

    const icon = sharp(iconPath)
    const targetW = Math.floor(rect.width * 0.8)
    const targetH = Math.floor(rect.height * 0.8)
    const resized = await icon
        .resize(targetW, targetH, {
            fit: 'contain',
            background: { r: 0, g: 0, b: 0, alpha: 0 },
        })
        .png()
        .toBuffer()
    const left = rect.x + Math.floor((rect.width - targetW) / 2)
    const top = rect.y + Math.floor((rect.height - targetH) / 2)

    return sharp(inputPng)
        .composite([{ input: resized, left, top }])
        .png({ compressionLevel: 3 })
        .toBuffer()
}

/**
 * 主流程
 * @param {string} srcImg 源 PNG
 * @param {string} srcXml 贴图 XML
 * @param {string} outputName 输出名（不带扩展名）
 */
async function iconModifier(srcImg, srcXml, outputName) {
    await fs.promises.mkdir(OUTPUT_PATH, { recursive: true })
    const tgImg = path.join(OUTPUT_PATH, `${outputName}.png`)
    const tgXml = path.join(OUTPUT_PATH, `${outputName}.xml`)
    const rnImg = path.join(OUTPUT_PATH, `${outputName}.dds`)

    let imgBuf = await readFile(srcImg)
    const coords = await parseCoordinates(srcXml)

    if (coords.length !== Object.keys(colors).length) {
        throw new Error(`坐标数量(${coords.length})与 colors 键数(${Object.keys(colors).length})不一致`)
    }

    for (const c of coords) {
        const rect = { x: c.x, y: c.y, width: c.width, height: c.height }
        imgBuf = await clearRect(imgBuf, rect)
        const conf = colors[c.name]
        if (typeof conf === 'string' && conf.endsWith('.png')) {
            imgBuf = await pasteIcon(imgBuf, rect, conf)
            console.log(`已应用图标: ${conf} -> ${c.name}`)
        } else if (Array.isArray(conf) && conf.length >= 3) {
            const rgba = /** @type {[number,number,number,number]} */ (conf.length === 4 ? conf : [...conf, 255])
            imgBuf = await drawCircle(imgBuf, rect, rgba)
            console.log(`已绘制圆形: ${c.name} -> rgba(${rgba.join(',')})`)
        }
    }

    await writeFile(tgImg, imgBuf)
    await fs.promises.copyFile(srcXml, tgXml)
    await fs.promises.rename(tgImg, rnImg)
}

module.exports = { iconModifier }

