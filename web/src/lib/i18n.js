// Messages of the plain-language summaries and the area panel (lib/plain.js, components/OutlookExplorer.astro).
// English is authoritative. Amharic (am) and Afaan Oromo (om) are DRAFTS written without a native-speaker review: they are
// shown only with ?lang=am or ?lang=om, under a banner, and REVIEWED stays false until a native speaker has checked them
// (then the language switch can be offered on the pages). Place names stay as in the OCHA boundaries (English).

export const REVIEWED = { en: true, am: false, om: false };
export const LANGS = { en: 'English', am: 'አማርኛ (Amharic)', om: 'Afaan Oromoo' };

const M = {
  en: {
    below: 'below normal', near: 'near normal', above: 'above normal',
    Below: 'Below normal', Near: 'Near normal', Above: 'Above normal',
    and: 'and',
    favoured: 'For {target}, {cat} rainfall is the most likely outcome in {place}: a {p} chance, against about 33% in a normal year.',
    none: 'For {target}, no outcome is clearly favoured in {place}: the chances stay close to normal (about 1 in 3 each).',
    dry: 'No tercile forecast for {place}: the reference-period rainfall is too low for tercile categories (dry season).',
    expected: 'Expected rainfall is about {mean}',
    anomaly: ', {pct} {dir} the normal of {normal}',
    dirAbove: 'above', dirBelow: 'below',
    members: '; 8 in 10 of the forecast members give {lo} to {hi}',
    regionalHead: 'For {target}:',
    regionalLine: '{Cat} rainfall is favoured in {names} ({range} chance).',
    regionalNone: 'For {target}, no region clearly favours one outcome: the chances stay close to normal (about 1 in 3 each).',
    across: 'Across the area, expected rainfall is about {mean}, {pct} {dir} the normal of {normal}.',
    trackUnknownW: 'not available', trackUnknown: 'Its past performance here is not available.',
    trackLowW: 'no better than climatology', trackLow: 'In past years, forecasts made this way were no better here than assuming normal chances (1 in 3 each): treat this outlook with caution.',
    trackModestW: 'slightly better than climatology', trackModest: 'In past years, forecasts made this way were only slightly better here than assuming normal chances: a modest guide.',
    trackFairW: 'better than climatology', trackFair: 'In past years, forecasts made this way were better here than assuming normal chances.',
    trackGoodW: 'clearly better than climatology', trackGood: 'In past years, forecasts made this way were clearly better here than assuming normal chances.',
    tenths: 'Out of 10 seasons like this one: about {b} below normal, {n} near normal, {a} above normal.',
    inPlainWords: 'In plain words', yourArea: 'Your area', clickHint: 'Click the map or search for a place to see its outlook in words.',
    expectedRainfall: 'Expected rainfall', normal: 'normal', observed: 'Observed', trackHere: 'Track record here',
    skillScore: 'skill score', pastSeasons: 'past seasons', gridCells: 'grid cells', gridCell: 'grid cell',
    smallWoreda: 'This woreda is smaller than one grid cell: the values are those of the cell at its centre.',
    csv: "Download this area's cells (CSV)", copy: 'Copy link', copied: 'Link copied',
    Region: 'Region', Zone: 'Zone', Woreda: 'Woreda',
    draft: '',
  },
  am: {
    below: 'ከመደበኛ በታች', near: 'መደበኛ አካባቢ', above: 'ከመደበኛ በላይ',
    Below: 'ከመደበኛ በታች', Near: 'መደበኛ አካባቢ', Above: 'ከመደበኛ በላይ',
    and: 'እና',
    favoured: 'ለ{target}፣ በ{place} በጣም ሊከሰት የሚችለው {cat} ዝናብ ነው፤ ዕድሉ {p} ሲሆን፣ በመደበኛ ዓመት 33% ገደማ ነው።',
    none: 'ለ{target}፣ በ{place} በግልጽ የሚያመዝን ውጤት የለም፤ ዕድሎቹ ለመደበኛው ቅርብ ናቸው (እያንዳንዳቸው ከ3 አንድ ገደማ)።',
    dry: 'ለ{place} የሶስትዮሽ ትንበያ የለም፤ የማጣቀሻ ጊዜው ዝናብ ለሶስትዮሽ ምድቦች በጣም አነስተኛ ነው (ደረቅ ወቅት)።',
    expected: 'የሚጠበቀው ዝናብ {mean} ገደማ ነው',
    anomaly: '፤ ይህም ከመደበኛው {normal} {pct} {dir} ነው',
    dirAbove: 'በላይ', dirBelow: 'በታች',
    members: '፤ ከትንበያ አባላት 10ሩ 8ቱ ከ{lo} እስከ {hi} ይሰጣሉ',
    regionalHead: 'ለ{target}፦',
    regionalLine: 'በ{names} {Cat} ዝናብ ያመዝናል (ዕድሉ {range})።',
    regionalNone: 'ለ{target}፣ አንድን ውጤት በግልጽ የሚያመዝን ክልል የለም፤ ዕድሎቹ ለመደበኛው ቅርብ ናቸው (እያንዳንዳቸው ከ3 አንድ ገደማ)።',
    across: 'በአካባቢው በሙሉ የሚጠበቀው ዝናብ {mean} ገደማ ሲሆን፣ ከመደበኛው {normal} {pct} {dir} ነው።',
    trackUnknownW: 'አይገኝም', trackUnknown: 'እዚህ ያለፈው አፈጻጸሙ አይገኝም።',
    trackLowW: 'ከአየር ንብረት መረጃ የተሻለ አይደለም', trackLow: 'ባለፉት ዓመታት በዚህ መንገድ የተሰሩ ትንበያዎች እዚህ መደበኛ ዕድሎችን (እያንዳንዳቸው ከ3 አንድ) ከመገመት የተሻሉ አልነበሩም፤ ይህን ትንበያ በጥንቃቄ ይጠቀሙበት።',
    trackModestW: 'ከአየር ንብረት መረጃ በጥቂቱ የተሻለ', trackModest: 'ባለፉት ዓመታት በዚህ መንገድ የተሰሩ ትንበያዎች እዚህ መደበኛ ዕድሎችን ከመገመት በጥቂቱ ብቻ የተሻሉ ነበሩ፤ መጠነኛ መመሪያ ነው።',
    trackFairW: 'ከአየር ንብረት መረጃ የተሻለ', trackFair: 'ባለፉት ዓመታት በዚህ መንገድ የተሰሩ ትንበያዎች እዚህ መደበኛ ዕድሎችን ከመገመት የተሻሉ ነበሩ።',
    trackGoodW: 'ከአየር ንብረት መረጃ በግልጽ የተሻለ', trackGood: 'ባለፉት ዓመታት በዚህ መንገድ የተሰሩ ትንበያዎች እዚህ መደበኛ ዕድሎችን ከመገመት በግልጽ የተሻሉ ነበሩ።',
    tenths: 'እንደዚህ ካሉ 10 ወቅቶች፦ {b} ገደማ ከመደበኛ በታች፣ {n} መደበኛ አካባቢ፣ {a} ከመደበኛ በላይ።',
    inPlainWords: 'በቀላል ቋንቋ', yourArea: 'የእርስዎ አካባቢ', clickHint: 'ትንበያውን በቃላት ለማየት ካርታውን ይጫኑ ወይም ቦታ ይፈልጉ።',
    expectedRainfall: 'የሚጠበቀው ዝናብ', normal: 'መደበኛ', observed: 'የታየው', trackHere: 'እዚህ ያለው ያለፈ አፈጻጸም',
    skillScore: 'የብቃት ውጤት', pastSeasons: 'ያለፉ ወቅቶች', gridCells: 'የፍርግርግ ሕዋሳት', gridCell: 'የፍርግርግ ሕዋስ',
    smallWoreda: 'ይህ ወረዳ ከአንድ የፍርግርግ ሕዋስ ያነሰ ነው፤ እሴቶቹ በመሃሉ ያለው ሕዋስ ናቸው።',
    csv: 'የዚህን አካባቢ ሕዋሳት ያውርዱ (CSV)', copy: 'ማስፈንጠሪያውን ይቅዱ', copied: 'ተቀድቷል',
    Region: 'ክልል', Zone: 'ዞን', Woreda: 'ወረዳ',
    draft: 'ረቂቅ ትርጉም፦ በአፍ መፍቻ ተናጋሪ ገና አልተገመገመም። ትክክለኛው ጽሑፍ እንግሊዝኛው ነው። · Draft translation, not yet reviewed by a native speaker; the English text is authoritative.',
  },
  om: {
    below: 'giddugaleessaa gadi', near: 'giddugaleessa', above: 'giddugaleessaa ol',
    Below: 'Giddugaleessaa gadi', Near: 'Giddugaleessa', Above: 'Giddugaleessaa ol',
    and: 'fi',
    favoured: '{target}f, {place} keessatti rooba {cat} ta’uu caalaa danda’a: carraan isaa {p} dha; waggaa idilee keessatti %33 naannoo dha.',
    none: '{target}f, {place} keessatti bu’aan ifatti caalu hin jiru: carraan idilee irraa hin fagaatu (tokkoon tokkoon isaanii 3 keessaa 1 naannoo).',
    dry: '{place}f tilmaamni sadaasaa hin jiru: roobni yeroo wabii sadarkaalee sadaasaatiif baay’ee xiqqaa dha (yeroo gogaa).',
    expected: 'Roobni eegamu {mean} naannoo dha',
    anomaly: ', idilee {normal} irra {pct} {dir}',
    dirAbove: 'ol', dirBelow: 'gadi',
    members: '; miseensota tilmaamaa 10 keessaa 8n {lo} hanga {hi} kennu',
    regionalHead: '{target}f:',
    regionalLine: '{names} keessatti rooba {cat} caalaa ta’a (carraa {range}).',
    regionalNone: '{target}f, naannoon bu’aa tokko ifatti filatu hin jiru: carraan idilee irraa hin fagaatu (tokkoon tokkoon isaanii 3 keessaa 1 naannoo).',
    across: 'Bal’ina naannoo guutuu irratti roobni eegamu {mean} naannoo dha, idilee {normal} irra {pct} {dir}.',
    trackUnknownW: 'hin argamu', trackUnknown: 'Raawwiin isaa kan darbe asitti hin argamu.',
    trackLowW: 'haala qilleensaa irra hin caalu', trackLow: 'Waggoota darban keessatti, tilmaamni akkasitti hojjetame asitti carraa idilee (3 keessaa 1) yaaduu irra hin caallu: tilmaama kana of eeggannoon fayyadamaa.',
    trackModestW: 'haala qilleensaa irra xiqqoo caala', trackModest: 'Waggoota darban keessatti, tilmaamni akkasitti hojjetame asitti carraa idilee yaaduu irra xiqqoo qofa caala ture: qajeelfama giddugaleessaa dha.',
    trackFairW: 'haala qilleensaa irra caala', trackFair: 'Waggoota darban keessatti, tilmaamni akkasitti hojjetame asitti carraa idilee yaaduu irra caala ture.',
    trackGoodW: 'haala qilleensaa irra ifatti caala', trackGood: 'Waggoota darban keessatti, tilmaamni akkasitti hojjetame asitti carraa idilee yaaduu irra ifatti caala ture.',
    tenths: 'Yeroolee akkanaa 10 keessaa: gara {b} giddugaleessaa gadi, {n} giddugaleessa, {a} giddugaleessaa ol.',
    inPlainWords: 'Jecha salphaan', yourArea: 'Naannoo keessan', clickHint: 'Tilmaama jechaan ilaaluuf kaartaa tuqaa ykn bakka barbaadaa.',
    expectedRainfall: 'Rooba eegamu', normal: 'idilee', observed: 'Kan mul’ate', trackHere: 'Raawwii darbe asitti',
    skillScore: 'qabxii dandeettii', pastSeasons: 'yeroolee darban', gridCells: 'seelota kaartaa', gridCell: 'seelii kaartaa',
    smallWoreda: 'Aanaan kun seelii kaartaa tokko irra xiqqaa dha: gatiiwwan kan seelii gidduu isaa ti.',
    csv: 'Seelota naannoo kanaa buusaa (CSV)', copy: 'Linkii garagalchaa', copied: 'Garagalfameera',
    Region: 'Naannoo', Zone: 'Godina', Woreda: 'Aanaa',
    draft: 'Hiikkaa barruu: ammaaf dubbataa afaan dhalootaatiin hin sakatta’amne. Barruun Ingiliffaa isa sirrii dha. · Draft translation, not yet reviewed by a native speaker; the English text is authoritative.',
  },
};

export function t(lang, key, vars = {}) {
  const s = (M[lang] ?? M.en)[key] ?? M.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
}

export function langFromQuery(search) {
  const l = new URLSearchParams(search).get('lang');
  return l && M[l] ? l : 'en';
}
