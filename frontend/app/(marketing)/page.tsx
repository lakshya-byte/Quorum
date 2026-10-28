import Header from "./_components/Header";
import Hero from "./_components/Hero";
import CredibilityStrip from "./_components/CredibilityStrip";
import ArchitectureBento from "./_components/ArchitectureBento";
import ProofExplorer from "./_components/ProofExplorer";
import Quickstart from "./_components/Quickstart";
import Footer from "./_components/Footer";

export default function Home() {
  return (
    <>
      <Header />
      <main className="w-full pt-14 bg-[#07090e] min-h-[calc(100vh-3.5rem)]">
        <div className="flex flex-col w-full">
          <Hero />
          <CredibilityStrip />
          <ArchitectureBento />
          <ProofExplorer />
          <Quickstart />
        </div>
      </main>
      <Footer />
    </>
  );
}
