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
        short_mark: { type: String },
        tech_name: { type: String },
        // vehicle_cd: { type: Number },
        premium: { type: Number },
        collector_vehicle: { type: Number },
        earn_crystals: { type: Number },
        special: { type: Number },
        tank_icon: { type: String },
        mastery_65: { type: Number },
        mastery_85: { type: Number },
        mastery_95: { type: Number },
        ace: { type: Number },
        gather_date: { type: Date },
        insert_date: { type: Date },
        update_date: { type: Date },
    }, { collection: 'all_tanks' });

    return mongoose.model('all_tanks', TanksSchema);
}