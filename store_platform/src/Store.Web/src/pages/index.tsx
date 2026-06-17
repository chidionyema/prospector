import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { PageHero, Section } from '@/components/marketing/blocks';
import { fetchCatalog, Pack } from '@/lib/api/client';

interface HomeProps {
  packs: Pack[];
}

export default function Home({ packs }: HomeProps) {
  return (
    <MarketingLayout>
      <Seo title="Prospector Store - Business Packs" />

      <PageHero
        eyebrow="System Live • PASSes only"
        title={<span className="leading-tight tracking-tighter">Small business packs, built to launch.</span>}
        lead={
          <span className="text-text/80">
            Every pack is a grounded opportunity passed by the Prospector engine. 
            Includes Blueprint, GTM Plan, and Build Kit. £30 each.
          </span>
        }
        primary={{ 
          href: "#catalog", 
          label: "Browse Catalog",
          variant: 'prominent'
        }}
      />

      <Section
        bg="bg"
        width="7xl"
        title="Available Packs"
        intro="Grounded, verifiable, and ready to execute."
        className="!pt-4 !pb-12 md:!py-24"
      >
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 mt-12">
          {packs.map((pack) => (
            <div key={pack.id} className="bg-white border border-border rounded-xl p-6 shadow-sm hover:shadow-md transition-all group">
              <div className="flex justify-between items-start mb-6">
                <span className="font-mono text-[9px] font-bold text-primary px-2 py-0.5 border border-primary/20 bg-primary/5 uppercase rounded tracking-wide">
                  Pack
                </span>
                <span className="font-bold text-xl text-text tracking-tighter font-mono">{pack.price}</span>
              </div>
              
              <div className="mb-6">
                <h3 className="font-bold text-lg text-text leading-tight group-hover:text-primary transition-colors">{pack.title}</h3>
                <p className="text-sm text-text/70 mt-3 line-clamp-3 leading-relaxed">
                  {pack.oneLine}
                </p>
              </div>
              
              <div className="mt-auto pt-6 border-t border-border/50 flex items-center justify-between">
                <Link href={`/pack/${pack.id}`} className="text-sm font-bold text-text hover:text-primary transition-colors flex items-center gap-2">
                  View Details
                  <Icon name="arrowRight" size={14} />
                </Link>
                <button className="bg-primary text-white text-xs font-bold px-4 py-2 rounded-md hover:bg-primary/90 transition-colors">
                  Buy
                </button>
              </div>
            </div>
          ))}

          {packs.length === 0 && (
            <div className="col-span-full py-24 text-center border-2 border-dashed border-border rounded-xl">
              <p className="text-muted font-medium">The catalog is currently empty. Check back later.</p>
            </div>
          )}
        </div>
      </Section>
    </MarketingLayout>
  );
}

export const getServerSideProps: GetServerSideProps = async () => {
  try {
    const packs = await fetchCatalog();
    return {
      props: { packs }
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    return {
      props: { packs: [] }
    };
  }
};
