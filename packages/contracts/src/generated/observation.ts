import { z } from "zod"

export const ObservationSchema = z.object({ "changed": z.union([z.string(), z.null()]).default(null), "droppedCount": z.number().int().default(0), "elements": z.array(z.any()).optional(), "protocolVersion": z.string().default("1.0.0"), "screenshotRef": z.union([z.string(), z.null()]).default(null), "title": z.string().default(""), "url": z.string(), "viewport": z.any() })

