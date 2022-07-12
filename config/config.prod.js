module.exports = {
    mongoose: {
        client: {
            url: `mongodb://${process.env.APP_DB_URL}`,
            options: {
                useUnifiedTopology: true
            },
        },
    }
};