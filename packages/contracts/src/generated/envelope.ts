import { z } from "zod"

export const EnvelopeSchema = z.object({ "payload": z.record(z.string(), z.any()).optional(), "protocolVersion": z.string().default("1.0.0"), "type": z.string() })

