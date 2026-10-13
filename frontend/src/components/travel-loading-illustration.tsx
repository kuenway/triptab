// Decorative geometry only; LoadingState owns reveal/status timers.
export function TravelLoadingIllustration() {
  return <svg className="travel-loading-illustration" width="200" height="140" viewBox="0 0 200 140" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path className="travel-ground" d="M35 124H167" strokeDasharray="4 12" />
    <g className="travel-suitcase">
      <path d="M77 87L85 71H92" />
      <rect x="63" y="87" width="28" height="28" rx="5" fill="var(--paper)" />
      <path d="M71 94V108M83 94V108" stroke="var(--teal)" />
      <circle cx="68" cy="119" r="3" fill="var(--ink)" />
      <circle cx="86" cy="119" r="3" fill="var(--ink)" />
    </g>
    <g className="travel-body">
      <g strokeWidth="6">
        <path className="travel-leg travel-leg-back" d="M110 78L99 96L101 115H109" />
        <path className="travel-leg travel-leg-front" d="M110 78L123 95L121 115H130" />
      </g>
      <path d="M108 43Q105 44 104 50L102 74Q110 81 121 76V51Q120 45 116 43Z" fill="var(--teal)" />
      <path d="M110 43V48" stroke="var(--paper)" />
      <path d="M109 53L102 66L91 71M119 51L125 62L133 65" strokeWidth="4" />
      <circle cx="114" cy="28" r="10" fill="var(--paper)" />
      <path d="M123 26L127 30H123" />
      <path d="M104 23Q106 12 116 16Q123 17 124 23Z" fill="var(--teal)" />
      <path d="M104 23H129" />
      <circle cx="120" cy="28" r="1" fill="currentColor" stroke="none" />
    </g>
  </svg>;
}
