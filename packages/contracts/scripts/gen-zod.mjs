import { readFileSync, writeFileSync, readdirSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { jsonSchemaToZod } from "json-schema-to-zod";

const here = dirname(fileURLToPath(import.meta.url));
const schemaDir = resolve(here, "..", "schema");
const outDir = resolve(here, "..", "src", "generated");
mkdirSync(outDir, { recursive: true });

const pascal = (s) =>
  s.split(/[_-]/).map((w) => w[0].toUpperCase() + w.slice(1)).join("");

for (const file of readdirSync(schemaDir).filter((f) => f.endsWith(".schema.json"))) {
  const base = file.replace(".schema.json", "");
  const schema = JSON.parse(readFileSync(join(schemaDir, file), "utf8"));
  const name = `${pascal(base)}Schema`;
  const code = jsonSchemaToZod(schema, { name, module: "esm" });
  writeFileSync(join(outDir, `${base}.ts`), `${code}\n`);
  console.log(`gen-zod: wrote src/generated/${base}.ts`);
}
