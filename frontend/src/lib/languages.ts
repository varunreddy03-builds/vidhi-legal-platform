// English plus the 22 languages of the Eighth Schedule of the Constitution of India.
// quality: "full" = every main screen is translated; "core" = menus, sign-in and the home screen are translated and the
// rest shows in English (marked Beta in the language list until native speakers have checked it).
export interface Language {
  code: string;
  english: string;
  native: string;
  dir: "ltr" | "rtl";
  quality: "full" | "core";
  font?: () => Promise<unknown>;
}

const fonts = {
  deva: () => import("@fontsource-variable/noto-sans-devanagari"),
  beng: () => import("@fontsource-variable/noto-sans-bengali"),
  gujr: () => import("@fontsource-variable/noto-sans-gujarati"),
  guru: () => import("@fontsource-variable/noto-sans-gurmukhi"),
  knda: () => import("@fontsource-variable/noto-sans-kannada"),
  mlym: () => import("@fontsource-variable/noto-sans-malayalam"),
  orya: () => import("@fontsource-variable/noto-sans-oriya"),
  taml: () => import("@fontsource-variable/noto-sans-tamil"),
  telu: () => import("@fontsource-variable/noto-sans-telugu"),
  arab: () => import("@fontsource-variable/noto-sans-arabic"),
  olck: () => import("@fontsource-variable/noto-sans-ol-chiki"),
  mtei: () => import("@fontsource-variable/noto-sans-meetei-mayek"),
};

export const LANGUAGES: Language[] = [
  { code: "en", english: "English", native: "English", dir: "ltr", quality: "full" },
  { code: "as", english: "Assamese", native: "অসমীয়া", dir: "ltr", quality: "full", font: fonts.beng },
  { code: "bn", english: "Bengali", native: "বাংলা", dir: "ltr", quality: "full", font: fonts.beng },
  { code: "brx", english: "Bodo", native: "बड़ो", dir: "ltr", quality: "core", font: fonts.deva },
  { code: "doi", english: "Dogri", native: "डोगरी", dir: "ltr", quality: "core", font: fonts.deva },
  { code: "gu", english: "Gujarati", native: "ગુજરાતી", dir: "ltr", quality: "full", font: fonts.gujr },
  { code: "hi", english: "Hindi", native: "हिन्दी", dir: "ltr", quality: "full", font: fonts.deva },
  { code: "kn", english: "Kannada", native: "ಕನ್ನಡ", dir: "ltr", quality: "full", font: fonts.knda },
  { code: "ks", english: "Kashmiri", native: "كٲشُر", dir: "rtl", quality: "core", font: fonts.arab },
  { code: "kok", english: "Konkani", native: "कोंकणी", dir: "ltr", quality: "core", font: fonts.deva },
  { code: "mai", english: "Maithili", native: "मैथिली", dir: "ltr", quality: "core", font: fonts.deva },
  { code: "ml", english: "Malayalam", native: "മലയാളം", dir: "ltr", quality: "full", font: fonts.mlym },
  { code: "mni", english: "Manipuri (Meitei)", native: "ꯃꯩꯇꯩꯂꯣꯟ", dir: "ltr", quality: "core", font: fonts.mtei },
  { code: "mr", english: "Marathi", native: "मराठी", dir: "ltr", quality: "full", font: fonts.deva },
  { code: "ne", english: "Nepali", native: "नेपाली", dir: "ltr", quality: "full", font: fonts.deva },
  { code: "or", english: "Odia", native: "ଓଡ଼ିଆ", dir: "ltr", quality: "full", font: fonts.orya },
  { code: "pa", english: "Punjabi", native: "ਪੰਜਾਬੀ", dir: "ltr", quality: "full", font: fonts.guru },
  { code: "sa", english: "Sanskrit", native: "संस्कृतम्", dir: "ltr", quality: "core", font: fonts.deva },
  { code: "sat", english: "Santali", native: "ᱥᱟᱱᱛᱟᱲᱤ", dir: "ltr", quality: "core", font: fonts.olck },
  { code: "sd", english: "Sindhi", native: "سنڌي", dir: "rtl", quality: "core", font: fonts.arab },
  { code: "ta", english: "Tamil", native: "தமிழ்", dir: "ltr", quality: "full", font: fonts.taml },
  { code: "te", english: "Telugu", native: "తెలుగు", dir: "ltr", quality: "full", font: fonts.telu },
  { code: "ur", english: "Urdu", native: "اردو", dir: "rtl", quality: "full", font: fonts.arab },
];

export const LANGUAGE_BY_CODE = new Map(LANGUAGES.map((l) => [l.code, l]));
export const isLanguage = (code: string | null | undefined): code is string => !!code && LANGUAGE_BY_CODE.has(code);
