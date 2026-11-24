/**
 * Public display names for the brand registry (`data/brands.yaml`): brand_id to {ar, en}.
 * The public incident title is built from these and the structured enums only, never from free text.
 * `web/tests/unit/public-incident-title.test.ts` checks this table against `data/brands.yaml`.
 */
export const BRAND_NAMES: Readonly<Record<string, { ar: string; en: string }>> = {
  abu_dhabi_police: { ar: "القيادة العامة لشرطة أبوظبي", en: "Abu Dhabi Police" },
  dubai_police: { ar: "القيادة العامة لشرطة دبي", en: "Dubai Police" },
  moi_uae: { ar: "وزارة الداخلية", en: "Ministry of Interior UAE" },
  uae_pass: { ar: "الهوية الرقمية (UAE PASS)", en: "UAE PASS" },
  tamm_abu_dhabi: { ar: "تم", en: "TAMM (Abu Dhabi Government Services)" },
  icp_uae: { ar: "الهيئة الاتحادية للهوية والجنسية والجمارك وأمن المنافذ", en: "Federal Authority for Identity, Citizenship, Customs & Port Security (ICP)" },
  emirates_post: { ar: "بريد الإمارات", en: "Emirates Post" },
  salik: { ar: "سالك", en: "Salik" },
  rta_dubai: { ar: "هيئة الطرق والمواصلات", en: "Roads and Transport Authority (RTA) Dubai" },
  itc_abu_dhabi_darb: { ar: "أبوظبي للتنقل", en: "Abu Dhabi Mobility (formerly Integrated Transport Centre, ITC) - Darb tolls" },
  addc_taqa_distribution: { ar: "طاقة للتوزيع", en: "Abu Dhabi Distribution Company (ADDC) / TAQA Distribution" },
  dewa: { ar: "هيئة كهرباء ومياه دبي", en: "Dubai Electricity and Water Authority (DEWA)" },
  sewa: { ar: "هيئة كهرباء ومياه وغاز الشارقة", en: "Sharjah Electricity, Water and Gas Authority (SEWA)" },
  etisalat_by_eand: { ar: "اتصالات", en: "Etisalat by e&" },
  du: { ar: "دو", en: "du (Emirates Integrated Telecommunications)" },
  cbuae: { ar: "مصرف الإمارات العربية المتحدة المركزي", en: "Central Bank of the UAE" },
  fab: { ar: "بنك أبوظبي الأول", en: "First Abu Dhabi Bank (FAB)" },
  adcb: { ar: "بنك أبوظبي التجاري", en: "Abu Dhabi Commercial Bank (ADCB)" },
  emirates_nbd: { ar: "بنك الإمارات دبي الوطني", en: "Emirates NBD" },
  dib: { ar: "بنك دبي الإسلامي", en: "Dubai Islamic Bank" },
  mashreq: { ar: "بنك المشرق", en: "Mashreq" },
  adib: { ar: "مصرف أبوظبي الإسلامي", en: "Abu Dhabi Islamic Bank (ADIB)" },
  rakbank: { ar: "بنك رأس الخيمة الوطني", en: "RAKBANK" },
  emirates_islamic: { ar: "الإمارات الإسلامي", en: "Emirates Islamic" },
  falcon_demo_bank: { ar: "بنك الصقر التجريبي", en: "Falcon Demo Bank" },
};
