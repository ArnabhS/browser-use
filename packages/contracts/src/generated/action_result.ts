import { z } from "zod"

export const ActionResultSchema = z.object({ "errorCode": z.union([z.string(), z.null()]).default(null), "reason": z.string().default(""), "success": z.boolean() })

