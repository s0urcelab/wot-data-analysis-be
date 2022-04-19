'use strict';

const Controller = require('egg').Controller;
const dayjs = require('dayjs')

const hasKey = (params = {}, key) => params.hasOwnProperty(key)

class HomeController extends Controller {
    async index() {
        const { ctx } = this;

        ctx.body = 'api version 1.1'
        ctx.status = 200
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
            avatar: authorType ? 'https://s2.loli.net/2022/04/20/HmKjQs8ZqA5v296.jpg' : `https://joeschmoe.io/api/v1/${author}`,
            content,
            reply_to,
            at,
            ...atText && { at_text: atText },
            date: dayjs().toDate(),
        })

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
        ctx.service.tanks.getTankggList(ctx.params.ver);

        ctx.body = `开始保存${ctx.params.ver}版本tanks.gg列表`
        ctx.status = 200
    }

    // 手动触发采集
    async manualGather() {
        const { ctx, app } = this;

        await app.runSchedule('update_mastery')

        ctx.body = '手动更新击杀环数据完成'
        ctx.status = 200
    }

    // 统计信息 & 筛选项
    async preData() {
        const { ctx } = this;

        const [{ lastUpdate }] = await ctx.model.Tanks.aggregate()
            .group({ _id: null, lastUpdate: { '$max': '$update_date' } })
        const hasMastery = await ctx.model.Tanks.countDocuments({ mastery_95: { $exists: true } })
        const total = await ctx.model.Tanks.countDocuments({ tier: { $gte: 5 } })

        const nationGroup = await ctx.model.Tanks.aggregate()
            .group({ _id: '$nation' })
            .sort('_id')

        const types = ['lightTank', 'mediumTank', 'heavyTank', 'AT-SPG', 'SPG']
        const tiers = Array.from({ length: 10 }).map((_, idx) => idx + 1)

        ctx.body = {
            errCode: 0,
            data: {
                nations: nationGroup.map(v => v._id),
                types,
                tiers,
                total,
                hasMastery,
                lastUpdate,
            },
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
        }
        // 校验参数
        ctx.validate(rule, ctx.query)
        // 组装参数
        const { page = 1, size = 40 } = ctx.query
        const query = {
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

        // 设置响应内容和响应状态码
        ctx.body = {
            errCode: 0,
            data: {
                list,
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
