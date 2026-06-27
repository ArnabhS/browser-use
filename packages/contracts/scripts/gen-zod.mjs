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

/**
 * Recursively resolve $ref pointers of the form "#/$defs/<Name>" by inlining
 * the definition from `defs`. Handles:
 *   - { "$ref": "#/$defs/Foo", ...siblings }
 *   - { "allOf": [{ "$ref": "#/$defs/Foo" }], ...siblings }
 * Our models are non-recursive (Observation → Viewport, Element), so simple
 * recursive inlining terminates.
 */
function dereference(node, defs) {
  if (Array.isArray(node)) {
    return node.map((item) => dereference(item, defs));
  }
  if (node === null || typeof node !== "object") {
    return node;
  }

  // Handle { "allOf": [{ "$ref": "..." }], ...siblings } — Pydantic wrapper shape
  if (
    node.allOf &&
    Array.isArray(node.allOf) &&
    node.allOf.length === 1 &&
    node.allOf[0].$ref
  ) {
    const ref = node.allOf[0].$ref;
    const match = ref.match(/^#\/\$defs\/(.+)$/);
    if (match) {
      const defName = match[1];
      const resolved = dereference(JSON.parse(JSON.stringify(defs[defName])), defs);
      // Merge siblings (excluding allOf) over the resolved def
      const { allOf, ...siblings } = node;
      return { ...resolved, ...siblings };
    }
  }

  // Handle bare { "$ref": "#/$defs/Foo", ...siblings }
  if (node.$ref) {
    const match = node.$ref.match(/^#\/\$defs\/(.+)$/);
    if (match) {
      const defName = match[1];
      const resolved = dereference(JSON.parse(JSON.stringify(defs[defName])), defs);
      // Merge siblings (excluding $ref) over the resolved def
      const { $ref, ...siblings } = node;
      return { ...resolved, ...siblings };
    }
  }

  // Recurse through object properties
  const result = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === "$defs") {
      // Drop $defs — they've been inlined
      continue;
    }
    result[key] = dereference(value, defs);
  }
  return result;
}

for (const file of readdirSync(schemaDir).filter((f) => f.endsWith(".schema.json"))) {
  const base = file.replace(".schema.json", "");
  const schema = JSON.parse(readFileSync(join(schemaDir, file), "utf8"));
  const name = `${pascal(base)}Schema`;

  const defs = schema.$defs ?? {};
  const resolved = dereference(schema, defs);

  const code = jsonSchemaToZod(resolved, { name, module: "esm" });
  writeFileSync(join(outDir, `${base}.ts`), `${code}\n`);
  console.log(`gen-zod: wrote src/generated/${base}.ts`);
}
