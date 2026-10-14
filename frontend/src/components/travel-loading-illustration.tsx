// Fixed-length joints; CSS alternates stance and swing without runtime geometry.
function Leg({ side }: { side: "front" | "back" }) {
  return <g className={`travel-leg travel-leg-${side}`} data-leg={side === "front" ? "left" : "right"} transform="translate(110 78)" strokeWidth="6">
    <g className="travel-thigh">
      <path d="M0 0V20" />
      <g transform="translate(0 20)">
        <g className="travel-shin">
          <path d="M0 0V20" />
          <g transform="translate(0 20)">
            <g className="travel-foot"><path d="M-3 1Q-3 3-1 3H7" /></g>
          </g>
        </g>
      </g>
    </g>
  </g>;
}

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
      <Leg side="back" />
      <Leg side="front" />
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
