import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Dream Company Three-State Color System
        status: {
          green: '#639922',
          amber: '#BA7517',
          red: '#E24B4A',
          gray: '#888780',
        },
        // Department colors
        dept: {
          trading: '#3B82F6',
          dream: '#8B5CF6',
          governance: '#F59E0B',
          knowledge: '#10B981',
          hr: '#EC4899',
          cfo: '#F97316',
          support: '#6B7280',
        },
      },
    },
  },
  plugins: [],
};

export default config;
