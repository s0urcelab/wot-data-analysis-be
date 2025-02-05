const dayjs = require('dayjs')

// 拉取击杀环数据
const fetchMastery = async (ctx, lv) => {
    let stopped = false
    let page = 1

    // infinite loop
    while (!stopped) {
        const res = await ctx.curl('https://tbox.wot.360.cn/rank/more', {
            method: 'POST',
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
            // const { ranking, modify } = res.data.data
            const NOW = dayjs().toDate()
            const { ranking } = res.data.data
            // 官方数据采集时间不更新，改为本机时间
            const modify = dayjs().startOf('hour').toDate()
            if (ranking.length === 0) {
                stopped = true
            }

            const tankList = ranking.map(async (item, idx) => {
                const isExist = await ctx.model.Tanks.exists({ _id: item.tank_id })
                const rank = (page - 1) * 40 + idx + 1

                if (isExist) {
                    // 更新
                    return ctx.model.Tanks
                        .findByIdAndUpdate(item.tank_id, {
                            name: item.tank_name,
                            tank_icon: item.tank_icon,
                            [`mastery_${lv}`]: item.mastery,
                            update_date: modify,
                            ...lv === 95 && { rank },
                        }, (err, doc) => {
                            doc.rank_delta = doc.rank - rank
                            doc.save()
                        })

                }

                const ggRes = await ctx.model.Gg.findById(item.tank_id).select('-__v').lean()
                return ctx.model.Tanks.insertMany({
                    ...ggRes,
                    _id: item.tank_id,
                    premium: 1,
                    collector_vehicle: 0,
                    name: item.tank_name,
                    tank_icon: item.tank_icon,
                    [`mastery_${lv}`]: item.mastery,
                    insert_date: NOW,
                    update_date: modify,
                    ...lv === 95 && { rank },
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
        await ctx.service.tanks.refreshList()
        await fetchMastery(ctx, 65)
        await fetchMastery(ctx, 85)
        await fetchMastery(ctx, 95)
        
        await ctx.service.tanks.getTankggList()
        await ctx.service.tanks.checkFixVehicle()
    },
};