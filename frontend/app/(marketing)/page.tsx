import Header from "./_components/Header";
import Footer from "./_components/Footer";
import { Diagrams, EntryPoints, Faq, FinalCta, Flow, Hero, ProofStrip, Trust, Verification } from "./_components/Sections";

export default function Home() {
  return (
    <>
      <Header />
      <main id="main" className="w-full bg-bg">
        <Hero />
        <ProofStrip />
        <Flow />
        <Verification />
        <Diagrams />
        <EntryPoints />
        <Trust />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
