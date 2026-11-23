import { cookies } from "next/headers";
import type { Lang } from "./contracts";

/** The reader's language from the `fl_lang` cookie (default Arabic), for server-rendered pages. */
export async function serverLang(): Promise<Lang> {
  return (await cookies()).get("fl_lang")?.value === "en" ? "en" : "ar";
}
