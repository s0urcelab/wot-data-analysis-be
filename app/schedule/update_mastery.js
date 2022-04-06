const dayjs = require('dayjs')

const MAS_LV = [65, 85, 95]

// 更新坦克列表
const refreshTankList = async (ctx) => {
    const res = await ctx.curl('https://wotgame.cn/wotpbe/tankopedia/api/vehicles/by_filters/', {
        data: {
            'filter[premium]': '0,1',
            'filter[language]': 'zh-cn',
        },
        dataType: 'json',
    });

    if (res.data && res.data.status === 'ok') {
        const NOW = dayjs().toDate()
        const { parameters, data } = res.data.data
        const allTanks = data.map(item => {
            const obj = item.reduce((acc, curr, idx) => ({
                ...acc,
                [parameters[idx]]: curr,
            }), {})
            return {
                ...obj,
                _id: obj.vehicle_cd,
                insert_date: NOW,
            }
        })

        try {
            await ctx.model.Tanks.insertMany(allTanks, { ordered: false });
        } catch (error) {
            console.warn('存在重复的tank_id，更新列表')
        }
    }
}


// 拉取击杀环数据
const fetchMastery = async (ctx, lv) => {
    let stopped = false
    let page = 1

    // infinite loop
    while (!stopped) {
        const res = await ctx.curl('https://tbox.wot.360.cn/rank/more', {
            data: {
                'percentile': lv,
                'rank_type': 'default',
                // 'type': '',
                'tier': '5,6,7,8,9,10',
                'sort': 'mastery',
                // 'tank_sort': '',
                // 'nation': '',
                'page': page,
                'size': 40,
            },
            dataType: 'json',
        });

        if (res.data && res.data.errno === 0) {
            const { ranking, modify } = res.data.data
            if (ranking.length === 0) {
                stopped = true
            }

            const tankList = ranking.map(item => {
                return ctx.model.Tanks
                    .findByIdAndUpdate(item.tank_id, {
                        tank_icon: item.tank_icon,
                        [`mastery_${lv}`]: item.mastery,
                        update_date: modify,
                    })
            })

            const historyList = ranking.map(item => {
                return ctx.model.History
                    .updateOne({
                        tank_id: item.tank_id,
                        insert_date: modify,
                    }, {
                        tank_id: item.tank_id,
                        [`mastery_${lv}`]: item.mastery,
                        insert_date: modify,
                    }, { upsert: true })
            })

            await Promise.all([...tankList, ...historyList])
            page++
        }
    }
}

module.exports = {
    schedule: {
        cron: '0 12 * * *', // 每天中午12点执行
        // interval: '1m', // 1 分钟间隔
        type: 'worker', // 指定 worker 执行
    },
    async task(ctx) {
        await refreshTankList(ctx)
        await Promise.all(MAS_LV.map(lv => fetchMastery(ctx, lv)))
    },
};