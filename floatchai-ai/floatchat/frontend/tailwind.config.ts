import type { Config } from "tailwindcss";

const config: Config = {
    darkMode: ["class"],
    content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
  	extend: {
  		colors: {
			ocean: {
				primary: "var(--color-ocean-primary)",
				light: "var(--color-ocean-light)",
				lighter: "var(--color-ocean-lighter)",
				deep: "var(--color-ocean-deep)",
			},
			bg: {
				base: "var(--color-bg-base)",
				surface: "var(--color-bg-surface)",
				elevated: "var(--color-bg-elevated)",
				subtle: "var(--color-bg-subtle)",
			},
			text: {
				primary: "var(--color-text-primary)",
				secondary: "var(--color-text-secondary)",
				muted: "var(--color-text-muted)",
				inverse: "var(--color-text-inverse)",
			},
			borderColor: {
				default: "var(--color-border-default)",
				subtle: "var(--color-border-subtle)",
			},
			sky: "var(--color-sky)",
			coral: "var(--color-coral)",
			seafoam: "var(--color-seafoam)",
			danger: "var(--color-danger)",
			"accent-sand": "var(--color-accent-sand)",
			"accent-moon": "var(--color-accent-moon)",
			"moon-silver": "var(--color-moon-silver)",
			"deep-purple": "var(--color-deep-purple)",
  			background: 'hsl(var(--background))',
  			foreground: 'hsl(var(--foreground))',
  			card: {
  				DEFAULT: 'hsl(var(--card))',
  				foreground: 'hsl(var(--card-foreground))'
  			},
  			popover: {
  				DEFAULT: 'hsl(var(--popover))',
  				foreground: 'hsl(var(--popover-foreground))'
  			},
  			primary: {
  				DEFAULT: 'hsl(var(--primary))',
  				foreground: 'hsl(var(--primary-foreground))'
  			},
  			secondary: {
  				DEFAULT: 'hsl(var(--secondary))',
  				foreground: 'hsl(var(--secondary-foreground))'
  			},
  			muted: {
  				DEFAULT: 'hsl(var(--muted))',
  				foreground: 'hsl(var(--muted-foreground))'
  			},
  			accent: {
  				DEFAULT: 'hsl(var(--accent))',
  				foreground: 'hsl(var(--accent-foreground))'
  			},
  			destructive: {
  				DEFAULT: 'hsl(var(--destructive))',
  				foreground: 'hsl(var(--destructive-foreground))'
  			},
  			border: 'hsl(var(--border))',
  			input: 'hsl(var(--input))',
  			ring: 'hsl(var(--ring))',
  			chart: {
  				'1': 'hsl(var(--chart-1))',
  				'2': 'hsl(var(--chart-2))',
  				'3': 'hsl(var(--chart-3))',
  				'4': 'hsl(var(--chart-4))',
  				'5': 'hsl(var(--chart-5))'
  			}
  		},
		fontFamily: {
			display: ["var(--font-display)", "Georgia", "serif"],
			body: ["var(--font-body)", "system-ui", "sans-serif"],
			mono: ["var(--font-mono)", "Courier New", "monospace"],
		},
  		borderRadius: {
			xs: '0.25rem',
			xl: '1rem',
			'2xl': '1.5rem',
			full: '9999px',
  			lg: 'var(--radius)',
  			md: 'calc(var(--radius) - 2px)',
  			sm: 'calc(var(--radius) - 4px)'
  		},
		boxShadow: {
			sm: '0 1px 3px rgba(26, 46, 53, 0.08)',
			md: '0 4px 12px rgba(26, 46, 53, 0.10)',
			lg: '0 8px 24px rgba(26, 46, 53, 0.12)',
		},
		transitionDuration: {
			fast: '100ms',
			normal: '200ms',
			slow: '300ms',
			slower: '500ms',
		},
		transitionTimingFunction: {
			default: 'cubic-bezier(0.4, 0, 0.2, 1)',
			in: 'cubic-bezier(0.4, 0, 1, 1)',
			out: 'cubic-bezier(0, 0, 0.2, 1)',
			spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
		},
  		keyframes: {
  			progress: {
  				'0%': { transform: 'translateX(-100%)' },
  				'100%': { transform: 'translateX(400%)' },
  			},
			'fade-slide-up': {
				'0%': { opacity: '0', transform: 'translateY(8px)' },
				'100%': { opacity: '1', transform: 'translateY(0)' },
			},
			'pulse-dot': {
				'0%, 100%': { transform: 'scale(0.9)', opacity: '0.5' },
				'50%': { transform: 'scale(1)', opacity: '1' },
			},
  		},
  		animation: {
  			progress: 'progress 1.5s ease-in-out infinite',
			'fade-slide-up': 'fade-slide-up 300ms cubic-bezier(0, 0, 0.2, 1)',
			'pulse-dot': 'pulse-dot 400ms ease-in-out infinite',
  		},
  	}
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
