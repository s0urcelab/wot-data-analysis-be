module.exports = app => {
    const mongoose = app.mongoose;
    const Schema = mongoose.Schema;

    const TanksSchema = new Schema({
        tank_id: { type: Number },
        mastery_65: { type: Number },
        mastery_85: { type: Number },
        mastery_95: { type: Number },
        ace: { type: Number },
        gather_date: { type: Date },
        insert_date: { type: Date },
        update_date: { type: Date },
    }, { collection: 'history_mastery' });

    return mongoose.model('history_mastery', TanksSchema);
}