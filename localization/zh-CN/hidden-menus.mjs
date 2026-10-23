import fs from "node:fs";

const [menuFile, listFile] = process.argv.slice(2);
const keys = JSON.parse(fs.readFileSync(listFile, "utf8"));
const menuSource = fs.readFileSync(menuFile, "utf8");
const missing = keys.filter((key) => !menuSource.includes(`key: "${key}"`));
if (missing.length > 0) throw new Error(`hidden-menus.json 中的菜单在 ${menuFile} 中不存在：${missing.join(", ")}`);
process.stdout.write(keys.join(","));
