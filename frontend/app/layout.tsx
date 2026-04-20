import type { Metadata } from 'next'
import { Crimson_Pro, IBM_Plex_Mono } from 'next/font/google'
import './globals.css'

const crimsonPro = Crimson_Pro({
  variable: '--font-display',
  subsets: ['latin'],
  weight: ['400', '600'],
  style: ['normal', 'italic'],
})

const ibmPlexMono = IBM_Plex_Mono({
  variable: '--font-mono-ui',
  subsets: ['latin'],
  weight: ['300', '400', '500'],
})

export const metadata: Metadata = {
  title: 'Oncology Research Platform',
  description: 'Secure collaborative workspace for oncology researchers',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      className={`${crimsonPro.variable} ${ibmPlexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  )
}
