const Service = require('egg').Service;
const dayjs = require('dayjs')

// 解析官方数据
const parseOfficialData = ({ parameters, data }) => {
    return data.reduce((ac, item) => {
        const obj = item.reduce((acc, curr, idx) => ({
            ...acc,
            [parameters[idx]]: curr,
        }), {})
        const _id = obj.vehicle_cd
        const newItem = {
            ...obj,
            _id,
        }
        return { ...ac, [_id]: newItem }
    }, {})
}

class TankService extends Service {
    
    // 官方全车列表
    async getOfficialList() {
        const { ctx } = this

        // 亚服全车列表
        const asia = ctx.curl('https://worldoftanks.asia/wotpbe/tankopedia/api/vehicles/by_filters/', {
            data: {
                'filter[premium]': '0,1',
                'filter[language]': 'en',
            },
            dataType: 'json',
        });

        // 国服全车列表
        const cn = ctx.curl('https://wotgame.cn/wotpbe/tankopedia/api/vehicles/by_filters/', {
            data: {
                'filter[premium]': '0,1',
                'filter[language]': 'zh-cn',
            },
            dataType: 'json',
        });

        const [asiaRes, cnRes] = await Promise.all([asia, cn])
        const { data: asiaData } = asiaRes
        const { data: cnData } = cnRes

        if (asiaData && cnData && asiaData.status === 'ok' && cnData.status === 'ok') {
            const asiaHash = parseOfficialData(asiaData.data)
            const cnHash = parseOfficialData(cnData.data)
            return [asiaHash, cnHash]
        }

        console.error('拉取官方数据失败！')
    }

    // tankgg全车列表
    async getTankggList(version) {
        const { ctx } = this

        const { data: { tanks: tankList } } = await ctx.curl('https://tanks.gg/api/list', {
            dataType: 'json',
        })

        const fetchTasks = tankList
            .map(({ slug }) => () => ctx.curl(`https://tanks.gg/api/${version}/tank/${slug}`, {
                dataType: 'json',
            }))

        const resList = await ctx.helper.sliceTaskAndRun(fetchTasks, {
            sliceSize: 20,
            sleepTime: 3000,
        })

        const NOW = dayjs().toDate()
        const ggList = resList.map(item => {
            const v = item.data.tank
            return {
                _id: v.tank_id,
                nation: v.nation,
                type: v.tags[0].name,
                role: v.tags[1].name,
                tier: v.tier,
                name: v.name,
                en_name: v.name,
                short_name: v.short_name,
                en_short_name: v.short_name,
                tech_name: v.id,
                insert_date: NOW,
            }
        })

        await this.ctx.model.Gg.insertMany(ggList, { ordered: false })
    }

    async refreshList() {
        const { ctx } = this

        let asiaHash = {}
        let cnHash = {}

        await ctx.helper.retry(async () => {
            const res = await this.getOfficialList()
            asiaHash = res[0]
            cnHash = res[1]
        }, 3)

        const NOW = dayjs().toDate()
        const mergeList = Object.keys(asiaHash)
            .map(_id => {
                const officialItem = cnHash[_id] || asiaHash[_id] || {}
                return {
                    ...officialItem,
                    en_name: asiaHash[_id].name,
                    en_short_name: asiaHash[_id].short_mark,
                    short_name: officialItem.short_mark,
                    premium: officialItem.premium,
                    collector_vehicle: officialItem.collector_vehicle,
                    insert_date: NOW,
                }
            })

        try {
            await ctx.model.Tanks.insertMany(mergeList, { ordered: false })
            // await this.ctx.model.Tanks.insertMany(mergeList)
            // const ids = mergeList.map(v => v._id)
            // const set = new Set(ids)
            // this.ctx.logger.error(ids.length, set.size)
            // console.log(`更新全部列表，插入${mergeList.length}条数据`)
        } catch (error) {
            // ctx.logger.error(error)
            console.log('更新部分列表')
        }
    }
}

module.exports = TankService;