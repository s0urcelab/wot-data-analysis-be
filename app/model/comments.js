module.exports = app => {
    const mongoose = app.mongoose;
    const Schema = mongoose.Schema;

    const CommSchema = new Schema({
        author: { type: String },
        author_type: { type: Number },
        avatar: { type: String },
        content: { type: String },
        reply_to: { type: String },
        at: { type: String },
        at_text: { type: String },
        date: { type: Date },
    }, { collection: 'comments' });

    return mongoose.model('comments', CommSchema);
}