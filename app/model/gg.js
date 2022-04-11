module.exports = app => {
    const mongoose = app.mongoose;
    const Schema = mongoose.Schema;

    const TanksSchema = new Schema({
        _id: { type: Number },
        nation: { type: String },
        type: { type: String },
        role: { type: String },
        tier: { type: Number },
        name: { type: String },
        en_name: { type: String },
        short_name: { type: String },
        en_short_name: { type: String },
        tech_name: { type: String },
        insert_date: { type: Date },
    }, { collection: 'tanksgg_list' });

    return mongoose.model('tanksgg_list', TanksSchema);
}