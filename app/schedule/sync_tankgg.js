module.exports = {
    schedule: {
        cron: '0 8 * * *', // 每天8点执行
        // interval: '1m', // 1 分钟间隔
        type: 'worker', // 指定 worker 执行
        immediate: true,
    },
    async task(ctx) {
        await ctx.service.tanks.getTankggList()
        await ctx.service.tanks.checkFixVehicle()
    },
};