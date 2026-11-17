// Runs once, the first time the MongoDB container initialises an empty data volume.
// Creates a database user for the app with the minimum rights it needs (read/write on ITS database only),
// so the app never connects with the root account.
const dbName = process.env.DB_NAME;
const user = process.env.MONGO_APP_USER;
const pwd = process.env.MONGO_APP_PASSWORD;
if (!dbName || !user || !pwd) {
  throw new Error("DB_NAME, MONGO_APP_USER and MONGO_APP_PASSWORD must be set");
}
db.getSiblingDB(dbName).createUser({ user, pwd, roles: [{ role: "readWrite", db: dbName }] });
