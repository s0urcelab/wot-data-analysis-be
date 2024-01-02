'use strict';

const Controller = require('egg').Controller;
const path = require('path')
const fs = require('fs')
const exec = require('util').promisify(require('child_process').exec)
const dayjs = require('dayjs')
const { nanoid } = require('nanoid')
const cheerio = require('cheerio')

const hasKey = (params = {}, key) => params.hasOwnProperty(key)

const WORK_DIR = '/usr/wot-data-analysis/badgesModifier'

const MAP_ARR_TO_OBJ = (arr, params) => arr.reduce((acc, curr, idx) => {
    acc[params[idx]] = curr
    return acc
}, {})

class HomeController extends Controller {
    async index() {
        const { ctx } = this;

        ctx.body = '1.1'
        ctx.status = 200
    }

    // 下载battleAtlas徽章文件
    async download() {
        const { ctx } = this

        const fileName = `battleAtlas.${ctx.request.query.t}`
        const filePath = path.join(WORK_DIR, 'output', `${ctx.request.query.n}.${ctx.request.query.t}`)

        ctx.attachment(fileName, {
            fallback: true,
            type: 'attachment', // [string] attachment/inline
        })
        // 文件大小
        const fileSize = fs.statSync(filePath).size
        ctx.set('Content-Length', fileSize)
        ctx.set('Content-Disposition', `attachment; filename=${fileName}`)
        ctx.body = fs.createReadStream(filePath)
            .on('end', () => {
                // 下载完成后删除文件
                fs.unlinkSync(filePath)
            })
    }

    // 上传battleAtlas处理
    async upload() {
        const { ctx } = this

        let ddsTempPath = ''
        let xmlTempPath = ''
        const outputName = nanoid()

        try {
            // 遍历处理多个文件
            for (const file of ctx.request.files) {
                ctx.logger.info(`UPLOAD: ${file.fieldname} ${file.filename} ${file.filepath}`)

                if (file.fieldname === 'dds') {
                    ddsTempPath = file.filepath
                }
                if (file.fieldname === 'xml') {
                    xmlTempPath = file.filepath
                }
            }

            if (!ddsTempPath || !xmlTempPath) {
                ctx.body = {
                    errCode: 10001,
                    data: '未上传指定文件',
                }
                return ctx.status = 200
            }

            const {
                stderr,
                stdout,
                code,
            } = await exec(`cd ${WORK_DIR} && (./modifier ${ddsTempPath} ${xmlTempPath} ${outputName})`)
                .catch(e => e)

            if (code || stderr) {
                ctx.body = {
                    errCode: 10003,
                    data: stderr,
                }
                return ctx.status = 200
            }

            ctx.body = {
                errCode: 0,
                data: outputName,
            }
            ctx.status = 200

        } finally {
            // 需要删除临时文件
            await ctx.cleanupRequestFiles();
        }
    }

    // 获取评论列表
    async getComments() {
        const { ctx } = this;

        const total = await ctx.model.Comments.countDocuments()
        const mainList = await ctx.model.Comments
            .find({ reply_to: { $exists: false } })
            .select('-__v')
            .lean()
        const searchTask = mainList.map(v => {
            return ctx.model.Comments
                .find({ reply_to: v._id })
                .sort('date')
                .select('-__v')
        })

        const subList = await Promise.all(searchTask)

        ctx.body = {
            errCode: 0,
            data: {
                list: mainList.map((comm, idx) => ({
                    ...comm,
                    replyList: subList[idx]
                })),
                total,
            },
        }
        ctx.status = 200
    }

    // 增加评论
    async addComment() {
        const { ctx } = this;
        let atText

        const rule = {
            author: 'string',
            avatar: 'string?',
            content: 'string',
            reply_to: 'string?',
            at: 'string?',
        }
        // 校验参数
        ctx.validate(rule, ctx.request.body)

        const {
            author,
            content,
            reply_to,
            at,
        } = ctx.request.body

        if (at) {
            const atComm = await ctx.model.Comments.findById(at).lean()
            atText = atComm.author || '无名氏'
        }
        const authorType = author === 'POWER_OVERWHELMING' ? 1 : 0
        await ctx.model.Comments.insertMany({
            author: authorType ? 's0urce' : author,
            author_type: authorType,
            avatar: authorType ? 'https://blog.src.moe/img/avatar.jpg' : `https://joeschmoe.io/api/v1/${author}`,
            content,
            reply_to,
            at,
            ...atText && { at_text: atText },
            date: dayjs().toDate(),
        })

        // push api通知
        if (!authorType) {
            await ctx.curl(ctx.helper.pushMsg(
                `${author}在wot.src.moe有新留言`,
                content,
                'https://wot.src.moe/message'
            ), { dataType: 'json' })
        }

        ctx.body = {
            errCode: 0,
            data: '评论成功！',
        }
        ctx.status = 200
    }

    // 保存tanks.gg坦克列表
    async storeTanksgg() {
        const { ctx } = this;

        // v11600
        ctx.service.tanks.getTankggList();

        ctx.body = `开始保存当前tanks.gg列表`
        ctx.status = 200
    }

    // 手动触发采集
    async manualGather() {
        const { ctx, app } = this;

        app.runSchedule('update_mastery')

        ctx.body = '开始手动更新击杀环数据'
        ctx.status = 200
    }

    // 统计信息 & 筛选项
    async preData() {
        const { ctx } = this;

        const rule = {
            pid: 'int?',
            pn: 'string?',
        }
        // 校验参数
        ctx.validate(rule, ctx.query)
        // 组装参数
        const { pid, pn } = ctx.query

        const [{ lastUpdate }] = await ctx.model.Tanks.aggregate()
            .group({ _id: null, lastUpdate: { '$max': '$update_date' } })
        // const hasMastery = await ctx.model.Tanks.countDocuments({ mastery_95: { $exists: true } })
        // const total = await ctx.model.Tanks.countDocuments({ tier: { $gte: 5 } })

        const nationGroup = await ctx.model.Tanks.aggregate()
            .group({ _id: '$nation' })
            .sort('_id')

        const types = ['lightTank', 'mediumTank', 'heavyTank', 'AT-SPG', 'SPG']
        const tiers = Array.from({ length: 10 }).map((_, idx) => idx + 1)

        let player = null
        if (pid && pn) {
            const { data: { data: { battles_count, wins_ratio, global_rating } } } = await ctx.curl(`https://wotgame.cn/wotup/profile/summary/?spa_id=${pid}&battle_type=random`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
                dataType: 'json',
            })

            const { data: wotboxHtml } = await ctx.curl(`https://wotbox.ouj.com/wotbox/index.php?r=default%2Findex&pn=${pn}`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
                dataType: 'text',
            })
            const $ = cheerio.load(wotboxHtml)

            player = {
                battTotal: battles_count,
                winRate: wins_ratio,
                wgr: global_rating,
                eff: +$('.power .num').text(),
                effDelta: +$('.power .float-num').text(),
            }
        }

        ctx.body = {
            errCode: 0,
            data: {
                nations: nationGroup.map(v => v._id),
                types,
                tiers,
                lastUpdate,
                player,
            },
        }
        ctx.status = 200
    }

    // 绑定玩家昵称
    async bindUser() {
        const { ctx } = this;

        const rule = {
            nickname: 'string',
        }
        // 校验参数
        ctx.validate(rule, ctx.request.body)

        const {
            nickname,
        } = ctx.request.body

        if (nickname.length < 4) {
            ctx.body = {
                errCode: 20001,
                msg: '玩家昵称至少4个字符',
            }
            ctx.status = 200
            return
        }

        const { data: { response: matchList } } = await ctx.curl(`https://wotgame.cn/zh-cn/community/accounts/search/?name=${nickname}`, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
            },
            dataType: 'json',
        })

        if (!matchList.length) {
            ctx.body = {
                errCode: 20002,
                msg: '没有找到您搜索的玩家',
            }
            ctx.status = 200
            return
        }

        ctx.body = {
            errCode: 0,
            data: matchList[0].account_id,
        }
        ctx.status = 200
    }

    // 全部坦克列表
    async tankList() {
        const { ctx } = this;

        const rule = {
            nation: 'string?',
            type: 'string?',
            tier: 'int?',
            premium: 'int?',
            collector_vehicle: 'int?',
            page: 'int?',
            size: 'int?',
            sort: 'string?',
            order: 'string?',
            player_id: 'int?',
        }
        // 校验参数
        ctx.validate(rule, ctx.query)
        // 组装参数
        const { page = 1, size = 40 } = ctx.query

        let playerVehiList = []
        if (hasKey(ctx.query, 'player_id')) {
            const { data: { data: { data, parameters } } } = await ctx.curl(`https://wotgame.cn/wotup/profile/vehicles/list/`, {
                method: 'POST',
                contentType: 'json',
                data: {
                    "battle_type": "random",
                    "only_in_garage": false,
                    "spa_id": +ctx.query.player_id,
                    "premium": [0, 1],
                    "collector_vehicle": [0, 1],
                    "nation": [],
                    "role": [],
                    "type": [],
                    "tier": [],
                    "language": "zh-cn",
                },
                dataType: 'json',
            })
            playerVehiList = data.map(item => MAP_ARR_TO_OBJ(item, parameters))
        }
        const addPlayerInfo = v => {
            if (!playerVehiList.length) {
                return v
            }
            const matchItem = playerVehiList.find(i => v._id === i.vehicle_cd)

            return {
                ...v,
                pl: {
                    mastery: matchItem.markOfMastery,
                    moe: matchItem.marksOnGun,
                }
            }
        }

        const query = {
            ...playerVehiList.length && { _id: { $in: playerVehiList.map(v => v.vehicle_cd) } },
            ...hasKey(ctx.query, 'nation') && { nation: ctx.query.nation },
            ...hasKey(ctx.query, 'type') && { type: ctx.query.type },
            ...hasKey(ctx.query, 'tier') && { tier: ctx.query.tier },
            ...hasKey(ctx.query, 'premium') && { premium: ctx.query.premium },
            ...hasKey(ctx.query, 'collector_vehicle') && { collector_vehicle: ctx.query.collector_vehicle },
        }
        const skip = (page - 1) * size
        const sort = ctx.query.sort && ctx.query.order
            ? `${ctx.query.order === 'ascend' ? '' : '-'}${ctx.query.sort}`
            : '-mastery_95'
        const total = await ctx.model.Tanks.countDocuments(query)
        const list = await ctx.model.Tanks
            .find(query)
            .select('-__v')
            .sort(sort)
            .skip(skip)
            .limit(size)
            .lean()

        // 设置响应内容和响应状态码
        ctx.body = {
            errCode: 0,
            data: {
                list: list.map(addPlayerInfo),
                total,
            },
        }
        ctx.status = 200
    }

    // 单车历史数据
    async singleTankHistory() {
        const { ctx } = this;

        const rule = {
            id: 'int',
            // page: 'int?',
            // size: 'int?',
        }
        // 校验参数
        ctx.validate(rule, ctx.query)
        // 组装参数
        const q = { tank_id: ctx.query.id }
        const list = await ctx.model.History
            .find(q)
            .select('-_id -__v -tank_id')
            .lean()

        // 设置响应内容和响应状态码
        ctx.body = {
            errCode: 0,
            data: {
                list: list.map(item => {
                    const { insert_date, ...rest } = item
                    return { date: insert_date, ...rest }
                }),
            },
        }
        ctx.status = 200
    }
}

module.exports = HomeController;
