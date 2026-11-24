import type { Lang } from "./contracts";

const ar = {
  "ob.title": "للمشغّل: المراقبة",
  "ob.trace": "عرض المسار في Phoenix",
  "ob.logs": "عرض السجلات في Grafana",
  "ob.dash": "لوحة القيادة في Grafana",
  "ob.notrace": "لا يوجد معرّف مسار لهذا الفحص (التتبّع كان متوقفًا)",
  "ob.row": "مسار Phoenix لهذا الفحص",
  "ob.mon.title": "المراقبة",
  "ob.mon.sub": "أدوات محلية على جهاز المشغّل فقط. لا تُعرض للعموم.",
  "ob.mon.grafana": "لوحات Grafana",
  "ob.mon.alerts": "تنبيهات Prometheus",
  "ob.mon.phoenix": "تتبّع Phoenix",
} as const;

const en = {
  "ob.title": "Operator: observability",
  "ob.trace": "View trace in Phoenix",
  "ob.logs": "View logs in Grafana",
  "ob.dash": "Command overview in Grafana",
  "ob.notrace": "No trace id for this check (tracing was off)",
  "ob.row": "Phoenix trace for this check",
  "ob.mon.title": "Monitoring",
  "ob.mon.sub": "Local tools on the operator's machine only. Never exposed publicly.",
  "ob.mon.grafana": "Grafana dashboards",
  "ob.mon.alerts": "Prometheus alerts",
  "ob.mon.phoenix": "Phoenix traces",
} as const;

export type ObsKey = keyof typeof en;

export const obT = (lang: Lang, key: ObsKey): string => (lang === "ar" ? ar : en)[key];
