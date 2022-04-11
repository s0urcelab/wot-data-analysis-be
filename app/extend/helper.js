// this 是 helper 对象，在其中可以调用其他 helper 方法
// this.ctx => context 对象
// this.app => application 对象

module.exports = {
    // 重试
    async retry(cb, count) {
        if (count === 0) return;

        try {
            await cb()
        } catch (error) {
            console.error(error)
            retry(cb, count - 1)
        }
    },
    // 挂起等待
    sleep(millisec) {
        return new Promise((resolve, reject) => {
            setTimeout(() => {
                resolve()
            }, millisec)
        })
    },
    // 任务拆分
    async sliceTaskAndRun(tasks = [], {
        sliceSize = 10,
        sleepTime = 1000,
        retryCount = 3,
    }) {
        const results = []

        if (sliceSize >= tasks.length) {
            await this.retry(async () => {
                const res = await Promise.all(tasks.map(task => task()))
                results.push(...res)
            }, retryCount)
            return results
        }

        let groupIdx = 1
        while (groupIdx * sliceSize < tasks.length) {
            const nowGroup = tasks.slice(groupIdx * (sliceSize - 1), groupIdx * sliceSize)
            await this.retry(async () => {
                const res = await Promise.all(nowGroup.map(task => task()))
                results.push(...res)
            }, retryCount)
            await this.sleep(sleepTime)

            groupIdx++
        }
        return results
    },
};