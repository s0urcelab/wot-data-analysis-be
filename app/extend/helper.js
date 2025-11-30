// this 是 helper 对象，在其中可以调用其他 helper 方法
// this.ctx => context 对象
// this.app => application 对象

module.exports = {
    // push msg templ
    pushMsg(title, content, url) {
        return `https://wework.src.moe/webhooks?u=me&t=${title}&c=${content}&l=${url}`
    },
    // 重试
    async retry(cb, count) {
        if (count === 0) return;

        try {
            await cb()
        } catch (error) {
            console.error(error)
            this.retry(cb, count - 1)
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

        const max = Math.ceil(tasks.length / sliceSize)
        for (let groupIdx = 1; groupIdx <= max; groupIdx++) {
            const nowGroup = tasks.slice(sliceSize * (groupIdx - 1), groupIdx * sliceSize)

            await this.retry(async () => {
                const res = await Promise.all(nowGroup.map(task => task()))
                results.push(...res)
            }, retryCount)
            await this.sleep(sleepTime)
        }

        return results
    },
    /**
     * 辅助函数：比较两个版本号（复用上一题的双指针逻辑，复杂度 O(L)）
     */
    compareVersion(v1, v2) {
        let i = 0, j = 0;
        const n = v1.length, m = v2.length;

        while (i < n || j < m) {
            let num1 = 0, num2 = 0;

            while (i < n && v1[i] !== '.') {
                num1 = num1 * 10 + (v1.charCodeAt(i) - 48);
                i++;
            }
            while (j < m && v2[j] !== '.') {
                num2 = num2 * 10 + (v2.charCodeAt(j) - 48);
                j++;
            }

            if (num1 > num2) return 1;
            if (num1 < num2) return -1;

            i++; j++;
        }
        return 0;
    },

    /**
     * 主函数：找出最大版本号
     * 时间复杂度：O(K * L) - K是数组长度，L是字符串长度
     */
    findMaxVersion(versions) {
        if (!versions || versions.length === 0) return null;

        // 假设第一个是最大的
        let maxVer = versions[0];

        // 从第二个开始遍历
        for (let i = 1; i < versions.length; i++) {
            // 如果当前版本比 maxVer 大，则更新 maxVer
            if (this.compareVersion(versions[i], maxVer) > 0) {
                maxVer = versions[i];
            }
        }

        return maxVer;
    },
};