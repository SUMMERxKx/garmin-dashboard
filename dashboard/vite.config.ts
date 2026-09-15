import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // "@/..." resolves to src/. This is the shadcn convention: every component it
    // generates imports `@/lib/utils`, so without this alias nothing it gives you
    // compiles. Vite needs it here and TypeScript needs it in tsconfig.app.json --
    // they are two separate resolvers and both have to agree.
    // `import.meta.dirname` rather than `__dirname` (gone in ESM) or
    // `new URL(...).pathname` -- the latter leaves the path percent-encoded, and this
    // project lives in a folder with a space in its name, so "Garmin%20Dashboard"
    // would not resolve.
    alias: { "@": `${import.meta.dirname}/src` },
  },
})
