import { z } from "zod"

export const EnvelopeSchema = z.object({ "id": z.union([z.string(), z.null()]).default(null), "payload": z.record(z.string(), z.any()).optional(), "protocolVersion": z.string().default("1.0.0"), "type": z.string() })

