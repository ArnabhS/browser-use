import { z } from "zod"

export const ActionCallSchema = z.object({ "args": z.record(z.string(), z.any()).optional(), "name": z.string() })

