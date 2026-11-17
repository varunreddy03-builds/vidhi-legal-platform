/** Help centre and first-run tour text, one file per language. The structure (same sections, same number of questions, same tour steps) is identical in every language: a test enforces it.
 *  English is the reference. Every other language is a translation that no native speaker has reviewed yet, and says so in `note`. */
export interface HelpContent {
  /** The language's own name. */
  name: string;
  /** Shown above the help text. English: empty. Others: that the text is a translation, not reviewed, and not legal advice. */
  note: string;
  /** Words for the buttons and links of the help centre, the tour and the sample-case link. `step` holds {n} and {total}. */
  ui: { tour: string; sample: string; helpCentre: string; next: string; back: string; skip: string; done: string; step: string; search: string; noResults: string; language: string; contact: string; sampleMade: string };
  tour: { title: string; text: string }[];
  sections: { title: string; items: { q: string; a: string }[] }[];
  /** More pages that exist in English only so far (English file only). The help centre shows them after the translated sections, under a line that says so. */
  extra?: { title: string; items: { q: string; a: string }[] }[];
}