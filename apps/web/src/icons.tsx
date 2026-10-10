const base = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

export const MicIcon = ({ size = 20 }: { size?: number }) => (
  <svg {...base} width={size} height={size}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
);
export const StopIcon = ({ size = 20 }: { size?: number }) => (
  <svg {...base} width={size} height={size}><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" /></svg>
);
export const SunIcon = () => (<svg {...base}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>);
export const MoonIcon = () => (<svg {...base}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>);
export const LockIcon = () => (<svg {...base} width={16} height={16}><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>);
export const SparkIcon = () => (<svg {...base} width={16} height={16}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>);
export const ReplayIcon = () => (<svg {...base} width={16} height={16}><path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" /></svg>);
export const ArrowIcon = () => (<svg {...base} width={16} height={16}><path d="M5 12h14M13 6l6 6-6 6" /></svg>);
export const CloudIcon = () => (<svg {...base} width={16} height={16}><path d="M7 18a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17 8.5a4.5 4.5 0 0 1 .5 9.5H7z" /></svg>);
export const ChipIcon = () => (<svg {...base} width={16} height={16}><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></svg>);
export const ShieldIcon = () => (<svg {...base} width={16} height={16}><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z" /><path d="M9 12l2 2 4-4" /></svg>);
export const BackIcon = () => (<svg {...base} width={16} height={16}><path d="M19 12H5M11 6l-6 6 6 6" /></svg>);
