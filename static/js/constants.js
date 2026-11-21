// Labels, colours and defaults shared across the UI.

export const DEFAULT_LOCATION = { lat: 28.6139, lon: 77.209, name: 'New Delhi', state: 'Delhi' };
export const CPCB_URL = 'https://airquality.cpcb.gov.in/AQI_India/';

export const CAT_COLORS = {
  good: '#2E7D32',
  satisfactory: '#7CB342',
  moderate: '#F9C623',
  poor: '#EF6C00',
  very_poor: '#C62828',
  severe: '#5D1A1A',
};

export const TIME_ICONS = { Morning: '🌅', Afternoon: '☀️', Evening: '🌆', Night: '🌙', Anytime: '⏱️' };
export const CATEGORY_ICONS = {
  commute: '🚇', outdoor: '🚶', indoor: '🏠', cooking: '🍳', health: '😷', community: '🤝',
};

export const AGE_LABELS = { infant: 'Baby', child: 'Child', teen: 'Teen', adult: 'Adult', senior: 'Senior' };
export const COND_LABELS = {
  asthma: 'asthma',
  copd: 'lung disease',
  heart: 'heart condition',
  pregnant: 'pregnant',
  allergies: 'allergies',
  diabetes: 'diabetes',
};
export const RISK_LABELS = {
  low: 'Low risk', moderate: 'Moderate risk', high: 'High risk', very_high: 'Very high risk',
};

export const MODE_LABELS = {
  car_solo: 'Car (alone)',
  car_pool: 'Carpool (2 people)',
  cab: 'Cab / taxi',
  auto: 'Auto-rickshaw',
  two_wheeler: 'Petrol two-wheeler',
  e_two_wheeler: 'Electric two-wheeler',
  bus: 'Bus',
  metro: 'Metro',
  walk_cycle: 'Walk / cycle',
  work_from_home: 'Work from home',
};
export const POLLUTING_MODES = ['car_solo', 'car_pool', 'cab', 'auto', 'two_wheeler'];

export const LANG_NAMES = { en: 'English', hi: 'Hindi', hinglish: 'Hinglish' };
/** BCP-47 codes so screen readers pronounce AI answers correctly. */
export const LANG_CODES = { en: 'en', hi: 'hi', hinglish: 'hi-Latn' };

export const DEFAULT_CHECKLIST = [
  { item: 'Wet-mop floors instead of sweeping', why: 'A dry broom kicks settled dust back into the air.' },
  { item: 'Keep windows shut during the smoggiest hours', why: 'Air out the house in the cleanest window instead.' },
  { item: 'No incense, dhoop or mosquito coils indoors', why: 'They add smoke right where you breathe.' },
  { item: 'Run the kitchen exhaust while cooking', why: 'It removes cooking particles at the source.' },
];
