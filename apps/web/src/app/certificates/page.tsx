'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'

// ── Certificate data ────────────────────────────────────────────────────────────

interface CertificateCard {
  id: string
  title: string
  subtitle: string
  description: string
  type: 'full' | 'summary'
  section: 'forms' | 'amendments'
}

const CERTIFICATES: CertificateCard[] = [
  {
    id: 'cargo-safety-equipment',
    title: 'Cargo Ship Safety Equipment Certificate',
    subtitle: 'SOLAS 1974/1978 Protocol — as amended through MSC.522(106)',
    description: 'Fire safety systems, life-saving appliances, navigational equipment, and COLREGs compliance.',
    type: 'full',
    section: 'forms',
  },
  {
    id: 'cargo-safety-construction',
    title: 'Cargo Ship Safety Construction Certificate',
    subtitle: 'SOLAS 1974/1978 Protocol — as amended through MSC.522(106)',
    description: 'Structural integrity, subdivision and stability, machinery and electrical installations.',
    type: 'full',
    section: 'forms',
  },
  {
    id: 'cargo-safety-radio',
    title: 'Cargo Ship Safety Radio Certificate',
    subtitle: 'SOLAS 1974/1988 Protocol — as amended through MSC.522(106)',
    description: 'GMDSS radio installations, sea areas, maintenance requirements, and radio log provisions.',
    type: 'full',
    section: 'forms',
  },
  {
    id: 'isps-certificate',
    title: 'International Ship Security Certificate',
    subtitle: 'SOLAS Chapter XI-2 / ISPS Code Part A',
    description: 'Ship security plan approval, security levels, security equipment, and CSO/SSO designations.',
    type: 'full',
    section: 'forms',
  },
  {
    id: 'record-of-equipment-e',
    title: 'Record of Equipment — Form E',
    subtitle: 'Cargo Ship Safety — amended by MSC.532(107)',
    description: 'Key amendments from the January 2026 supplement affecting the cargo ship Record of Equipment.',
    type: 'summary',
    section: 'amendments',
  },
  {
    id: 'record-of-equipment-p',
    title: 'Record of Equipment — Form P',
    subtitle: 'Passenger Ship Safety — amended by MSC.532(107)',
    description: 'Key amendments from the January 2026 supplement affecting the passenger ship Record of Equipment.',
    type: 'summary',
    section: 'amendments',
  },
]

// ── Shared form helpers ─────────────────────────────────────────────────────────

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="font-display text-sm font-bold text-[#2dd4bf] print:text-black uppercase tracking-wider
      border-b border-white/10 print:border-black/20 pb-1 mb-3 mt-6 print:mt-4">
      {children}
    </h3>
  )
}

function FormField({ label, wide, note }: { label: string; wide?: boolean; note?: string }) {
  return (
    <div className={wide ? 'col-span-full' : ''}>
      <p className="font-mono text-xs text-[#6b7594] print:text-gray-500 mb-0.5">
        {label}{note && <span className="align-super text-[10px] ml-0.5">{note}</span>}
      </p>
      <div className="border-b border-white/15 print:border-black/30 h-6" />
    </div>
  )
}

function FormFieldInline() {
  return <span className="inline-block border-b border-white/15 print:border-black/30 w-48 mx-1" />
}

function Checkbox({ label }: { label: string }) {
  return (
    <label className="flex items-center gap-2 font-mono text-xs text-[#f0ece4]/80 print:text-black">
      <span className="w-4 h-4 border border-white/20 print:border-black/40 rounded-sm flex-shrink-0" />
      {label}
    </label>
  )
}

function CertFormHeader({ onBack, title }: { onBack: () => void; title: string }) {
  return (
    <header className="print:hidden flex-shrink-0 flex items-center justify-between gap-3 px-4 py-3
      bg-[#111827]/95 backdrop-blur-md border-b border-white/8">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="w-9 h-9 flex items-center justify-center rounded-lg
          text-[#6b7594] hover:text-[#f0ece4] transition-colors" aria-label="Back">
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide leading-tight">
          {title}
        </h1>
      </div>
      <button onClick={() => window.print()}
        className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
          hover:brightness-110 rounded-lg px-3 py-1.5 transition-[filter]">
        Print / Save PDF
      </button>
    </header>
  )
}

function CertHeader({ title, conventionText }: { title: string; conventionText: string }) {
  return (
    <div className="text-center mb-8 print:mb-6">
      <div className="w-20 h-20 mx-auto mb-4 border-2 border-white/20 print:border-black/40 rounded-full
        flex items-center justify-center">
        <span className="font-mono text-xs text-[#6b7594] print:text-gray-500">Official<br/>Seal</span>
      </div>
      <h2 className="font-display text-2xl font-bold text-[#f0ece4] print:text-black tracking-wide uppercase">
        {title}
      </h2>
      <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 mt-2">{conventionText}</p>
      <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 mt-1">
        under the authority of the Government of
      </p>
      <FormField label="" wide />
      <p className="font-mono text-[10px] text-[#6b7594] print:text-gray-500 italic">(name of the State)</p>
    </div>
  )
}

function ShipParticulars() {
  return (
    <>
      <SectionHeading>Particulars of Ship</SectionHeading>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1 mb-6">
        <FormField label="Name of ship" />
        <FormField label="Distinctive number or letters" />
        <FormField label="Port of registry" />
        <FormField label="Gross tonnage" />
        <FormField label="IMO Number" />
        <FormField label="Date keel laid or conversion commenced" />
      </div>
    </>
  )
}

function ShipTypeCheckboxes({ types }: { types: string[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-6">
      {types.map(t => <Checkbox key={t} label={t} />)}
    </div>
  )
}

function ValidityBlock() {
  return (
    <>
      <SectionHeading>Validity</SectionHeading>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1 mb-6">
        <FormField label="This certificate is valid until" />
        <FormField label="Completion date of the survey" />
      </div>
    </>
  )
}

function IssueBlock() {
  return (
    <>
      <SectionHeading>Issued At</SectionHeading>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1 mb-8">
        <FormField label="Place of issue" />
        <FormField label="Date of issue" />
      </div>
      <div className="mb-8">
        <FormField label="Signature of duly authorized official issuing the certificate" />
        <p className="font-mono text-[10px] text-[#6b7594] print:text-gray-500 italic mt-1">(Seal or stamp of the authority, as appropriate)</p>
      </div>
    </>
  )
}

function AnnualSurveyEndorsements() {
  return (
    <>
      <SectionHeading>Endorsement for Mandatory Annual Survey / Unscheduled Inspection</SectionHeading>
      {[1, 2, 3, 4].map(n => (
        <div key={n} className="mb-4 font-mono text-xs text-[#f0ece4]/80 print:text-black">
          <p className="font-semibold mb-1 text-[#2dd4bf] print:text-black">Survey {n}</p>
          <div className="grid grid-cols-3 gap-x-6 gap-y-1">
            <FormField label="Signed" />
            <FormField label="Place" />
            <FormField label="Date" />
          </div>
        </div>
      ))}
    </>
  )
}

function ExtensionBlock() {
  return (
    <>
      <SectionHeading>Extension of Certificate</SectionHeading>
      <div className="mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black">
        <p className="mb-2">Where applicable, in accordance with regulation I/14 of the Convention, the validity of this certificate is extended to:</p>
        <div className="grid grid-cols-2 gap-x-8 gap-y-1">
          <FormField label="Date of extension" />
          <FormField label="Signed" />
          <FormField label="Place" />
        </div>
      </div>
    </>
  )
}

// ── Full form: Cargo Ship Safety Equipment Certificate ──────────────────────────

function CargoShipSafetyForm({ onBack }: { onBack: () => void }) {
  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <CertFormHeader onBack={onBack} title="Cargo Ship Safety Equipment Certificate" />

      <main className="flex-1 overflow-y-auto">
        <div className="cert-print-area max-w-[210mm] mx-auto px-6 py-8 md:px-12
          bg-[#0a0e1a] print:bg-white print:text-black print:px-[20mm] print:py-[15mm]">

          <CertHeader
            title="Cargo Ship Safety Equipment Certificate"
            conventionText="Issued under the provisions of the International Convention for the Safety of Life at Sea, 1974, as modified by the Protocol of 1978 relating thereto"
          />

          <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 mb-1 italic">
            by <FormFieldInline /> <span className="text-[10px] italic">(person or organization authorized)</span>
          </p>

          <ShipParticulars />

          <SectionHeading>Type of Ship <span className="text-[10px] font-normal align-super print:text-gray-500">2</span></SectionHeading>
          <ShipTypeCheckboxes types={['Bulk carrier', 'Oil tanker', 'Chemical tanker', 'Gas carrier', 'Containership', 'Cargo ship other than above']} />

          <SectionHeading>Certification</SectionHeading>
          <div className="space-y-3 mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black leading-relaxed">
            <p>THIS IS TO CERTIFY that the above ship has been surveyed in accordance with the requirements of regulation I/8 of the Convention and that the survey showed that:</p>
            <ol className="list-decimal list-outside ml-6 space-y-2">
              <li>the fire safety systems and appliances and fire control plans were found to comply with the requirements of the Convention;</li>
              <li>the life-saving appliances and equipment were provided in accordance with the requirements of the Convention;</li>
              <li>the ship was provided with a line-throwing appliance and radio installations used in life-saving appliances in accordance with the requirements of the Convention;</li>
              <li>the ship was provided with navigational equipment and publications, and the pilot embarkation equipment, in accordance with the requirements of the Convention;</li>
              <li>the ship was provided with lights, shapes, means of making sound signals and distress signals in accordance with the requirements of the Convention and the International Regulations for Preventing Collisions at Sea in force;</li>
              <li>in all other respects the ship complied with the relevant requirements of the Convention;</li>
              <li>whether or not the ship has been provided with an alternative design or arrangement in accordance with regulation II-2/17 or III/38 of the Convention: Yes / No <span className="align-super text-[10px]">3</span>;</li>
              <li>a Document of Approval of the alternative design and arrangement for the ship has been / has not been <span className="align-super text-[10px]">3</span> issued;</li>
              <li>whether or not an Exemption Certificate has been / has not been <span className="align-super text-[10px]">3</span> issued.</li>
            </ol>
          </div>

          <SectionHeading>Trade Area</SectionHeading>
          <div className="mb-6">
            <FormField label="Trade area limit under regulation III/26.1.1.1" />
          </div>

          <SectionHeading>Government Inspection</SectionHeading>
          <div className="space-y-2 mb-6">
            <Checkbox label="Mandatory annual surveys" />
            <Checkbox label="Unscheduled inspections" />
          </div>

          <ValidityBlock />
          <IssueBlock />

          <div className="page-break-before" />
          <SectionHeading>Endorsement for Intermediate Survey (tankers 10+ years) <span className="text-[10px] font-normal align-super">4</span></SectionHeading>
          <div className="mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black">
            <p className="mb-2">THIS IS TO CERTIFY that at an intermediate survey required by regulation I/10 the ship was found to comply with the relevant requirements of the Convention.</p>
            <div className="grid grid-cols-2 gap-x-8 gap-y-1">
              <FormField label="Signed" />
              <FormField label="Place" />
              <FormField label="Date" />
            </div>
          </div>

          <AnnualSurveyEndorsements />
          <ExtensionBlock />

          <div className="border-t border-white/10 print:border-black/20 pt-4 mt-8">
            <p className="font-display text-sm font-bold text-[#f0ece4] print:text-black mb-2">Footnotes</p>
            <ol className="list-decimal list-outside ml-5 space-y-1 font-mono text-[10px] text-[#6b7594] print:text-gray-600 leading-snug">
              <li>For oil tankers, chemical tankers and gas carriers only.</li>
              <li>Delete as appropriate. &quot;Containership&quot; added by MSC.532(107) and MSC.534(107).</li>
              <li>Delete as appropriate.</li>
              <li>This endorsement applies to tankers of 10 years of age and over.</li>
              <li>Insert the date of expiry as specified by the Administration in accordance with regulation I/14(a) of the Convention.</li>
            </ol>
          </div>
        </div>
      </main>
    </div>
  )
}

// ── Full form: Cargo Ship Safety Construction Certificate ────────────────────────

function ConstructionSafetyForm({ onBack }: { onBack: () => void }) {
  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <CertFormHeader onBack={onBack} title="Cargo Ship Safety Construction Certificate" />

      <main className="flex-1 overflow-y-auto">
        <div className="cert-print-area max-w-[210mm] mx-auto px-6 py-8 md:px-12
          bg-[#0a0e1a] print:bg-white print:text-black print:px-[20mm] print:py-[15mm]">

          <CertHeader
            title="Cargo Ship Safety Construction Certificate"
            conventionText="Issued under the provisions of the International Convention for the Safety of Life at Sea, 1974, as modified by the Protocol of 1978 relating thereto"
          />

          <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 mb-1 italic">
            by <FormFieldInline /> <span className="text-[10px] italic">(person or organization authorized)</span>
          </p>

          <ShipParticulars />

          <SectionHeading>Type of Ship</SectionHeading>
          <ShipTypeCheckboxes types={['Bulk carrier', 'Oil tanker', 'Chemical tanker', 'Gas carrier', 'Containership', 'Cargo ship other than above']} />

          <SectionHeading>Certification</SectionHeading>
          <div className="space-y-3 mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black leading-relaxed">
            <p>THIS IS TO CERTIFY that the above ship has been surveyed in accordance with the requirements of regulation I/10 of the Convention and that the survey showed that:</p>
            <ol className="list-decimal list-outside ml-6 space-y-2">
              <li>the condition of the hull, machinery and equipment as defined in the above regulation was found satisfactory and the ship complied with the relevant requirements of Chapters II-1 and II-2 of the Convention (other than those relating to fire safety systems and appliances);</li>
              <li>the last two bottom surveys of the outside of the ship&apos;s bottom took place on <FormFieldInline /> and <FormFieldInline />;</li>
              <li>whether or not an Exemption Certificate has been / has not been <span className="align-super text-[10px]">*</span> issued;</li>
              <li>whether or not the ship has been provided with an alternative design or arrangement in accordance with regulation II-1/55 of the Convention: Yes / No <span className="align-super text-[10px]">*</span>.</li>
            </ol>
          </div>

          <ValidityBlock />
          <IssueBlock />

          <div className="page-break-before" />
          <SectionHeading>Endorsement for Intermediate Survey</SectionHeading>
          <div className="mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black">
            <p className="mb-2">THIS IS TO CERTIFY that at an intermediate survey required by regulation I/10 the ship was found to comply with the relevant requirements of the Convention.</p>
            <div className="grid grid-cols-2 gap-x-8 gap-y-1">
              <FormField label="Signed" />
              <FormField label="Place" />
              <FormField label="Date" />
            </div>
          </div>

          <AnnualSurveyEndorsements />
          <ExtensionBlock />

          <div className="border-t border-white/10 print:border-black/20 pt-4 mt-8">
            <p className="font-display text-sm font-bold text-[#f0ece4] print:text-black mb-2">Footnotes</p>
            <ol className="font-mono text-[10px] text-[#6b7594] print:text-gray-600 leading-snug list-none space-y-1 ml-2">
              <li>* Delete as appropriate.</li>
            </ol>
          </div>
        </div>
      </main>
    </div>
  )
}

// ── Full form: Cargo Ship Safety Radio Certificate ──────────────────────────────

function RadioSafetyForm({ onBack }: { onBack: () => void }) {
  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <CertFormHeader onBack={onBack} title="Cargo Ship Safety Radio Certificate" />

      <main className="flex-1 overflow-y-auto">
        <div className="cert-print-area max-w-[210mm] mx-auto px-6 py-8 md:px-12
          bg-[#0a0e1a] print:bg-white print:text-black print:px-[20mm] print:py-[15mm]">

          <CertHeader
            title="Cargo Ship Safety Radio Certificate"
            conventionText="Issued under the provisions of the International Convention for the Safety of Life at Sea, 1974, as modified by the Protocol of 1988 relating thereto"
          />

          <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 mb-1 italic">
            by <FormFieldInline /> <span className="text-[10px] italic">(person or organization authorized)</span>
          </p>

          <ShipParticulars />

          <SectionHeading>Sea Areas</SectionHeading>
          <div className="space-y-2 mb-6">
            <Checkbox label="Sea Area A1" />
            <Checkbox label="Sea Area A2" />
            <Checkbox label="Sea Area A3" />
            <Checkbox label="Sea Area A4" />
          </div>

          <SectionHeading>Certification</SectionHeading>
          <div className="space-y-3 mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black leading-relaxed">
            <p>THIS IS TO CERTIFY that the above ship has been surveyed in accordance with the requirements of regulation I/9 of the Convention and that the survey showed that:</p>
            <ol className="list-decimal list-outside ml-6 space-y-2">
              <li>the ship complied with the requirements of the Convention regarding radio installations;</li>
              <li>the functioning of the radio installations used in life-saving appliances was found satisfactory;</li>
              <li>whether or not an Exemption Certificate has been / has not been <span className="align-super text-[10px]">*</span> issued.</li>
            </ol>
          </div>

          <SectionHeading>Radio Equipment Details</SectionHeading>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1 mb-6">
            <FormField label="Primary GMDSS system" />
            <FormField label="Secondary means of alerting" />
            <FormField label="NAVTEX receiver" />
            <FormField label="EGC (SafetyNET)" />
            <FormField label="HF DSC / radio installation" />
            <FormField label="Inmarsat ship earth station" />
            <FormField label="MF/HF radio installation" />
            <FormField label="Satellite EPIRB" />
            <FormField label="VHF radio installation" />
            <FormField label="SART / AIS-SART" />
          </div>

          <SectionHeading>Maintenance Method</SectionHeading>
          <div className="space-y-2 mb-6">
            <Checkbox label="Duplication of equipment" />
            <Checkbox label="Shore-based maintenance" />
            <Checkbox label="At-sea maintenance capability" />
          </div>

          <ValidityBlock />
          <IssueBlock />

          <div className="page-break-before" />
          <AnnualSurveyEndorsements />
          <ExtensionBlock />

          <div className="border-t border-white/10 print:border-black/20 pt-4 mt-8">
            <p className="font-display text-sm font-bold text-[#f0ece4] print:text-black mb-2">Footnotes</p>
            <ol className="font-mono text-[10px] text-[#6b7594] print:text-gray-600 leading-snug list-none space-y-1 ml-2">
              <li>* Delete as appropriate.</li>
              <li>Sea area designations per SOLAS Chapter IV, Regulation 2.</li>
            </ol>
          </div>
        </div>
      </main>
    </div>
  )
}

// ── Full form: International Ship Security Certificate ───────────────────────────

function ISPSCertificateForm({ onBack }: { onBack: () => void }) {
  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <CertFormHeader onBack={onBack} title="International Ship Security Certificate" />

      <main className="flex-1 overflow-y-auto">
        <div className="cert-print-area max-w-[210mm] mx-auto px-6 py-8 md:px-12
          bg-[#0a0e1a] print:bg-white print:text-black print:px-[20mm] print:py-[15mm]">

          <CertHeader
            title="International Ship Security Certificate"
            conventionText="Issued under the provisions of the International Convention for the Safety of Life at Sea, 1974, as amended, Chapter XI-2 and the International Ship and Port Facility Security (ISPS) Code, Part A"
          />

          <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 mb-1 italic">
            by <FormFieldInline /> <span className="text-[10px] italic">(name of the Administration)</span>
          </p>
          <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 mb-1 italic">
            or <FormFieldInline /> <span className="text-[10px] italic">(Recognized Security Organization)</span>
          </p>

          <ShipParticulars />

          <SectionHeading>Type of Ship</SectionHeading>
          <ShipTypeCheckboxes types={['Passenger ship', 'Passenger high-speed craft', 'Cargo high-speed craft', 'Bulk carrier', 'Oil tanker', 'Chemical tanker', 'Gas carrier', 'Containership', 'Mobile offshore drilling unit', 'Other cargo ship']} />

          <SectionHeading>Certification</SectionHeading>
          <div className="space-y-3 mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black leading-relaxed">
            <p>THIS IS TO CERTIFY THAT:</p>
            <ol className="list-decimal list-outside ml-6 space-y-2">
              <li>the security system and any associated security equipment of the ship has been verified in accordance with section 19.1 of Part A of the ISPS Code;</li>
              <li>the verification showed that the security system and any associated security equipment of the ship is in all respects satisfactory and that the ship complies with the applicable requirements of Chapter XI-2 of the Convention and Part A of the ISPS Code;</li>
              <li>the ship is provided with an approved Ship Security Plan.</li>
            </ol>
          </div>

          <SectionHeading>Ship Security Plan</SectionHeading>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1 mb-6">
            <FormField label="Approval date of the Ship Security Plan" />
            <FormField label="Approved by (name of Administration or RSO)" />
          </div>

          <SectionHeading>Security Personnel</SectionHeading>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1 mb-6">
            <FormField label="Company Security Officer (CSO)" />
            <FormField label="Ship Security Officer (SSO)" />
          </div>

          <ValidityBlock />
          <IssueBlock />

          <div className="page-break-before" />
          <SectionHeading>Endorsement for Intermediate Verification</SectionHeading>
          <div className="mb-6 font-mono text-xs text-[#f0ece4]/80 print:text-black">
            <p className="mb-2">THIS IS TO CERTIFY that at an intermediate verification required by section 19.1.1 of Part A of the ISPS Code the ship was found to comply with the relevant provisions of Chapter XI-2 of the Convention and Part A of the ISPS Code.</p>
            <div className="grid grid-cols-2 gap-x-8 gap-y-1">
              <FormField label="Signed" />
              <FormField label="Place" />
              <FormField label="Date" />
            </div>
          </div>

          <SectionHeading>Endorsement for Additional Verification</SectionHeading>
          {[1, 2].map(n => (
            <div key={n} className="mb-4 font-mono text-xs text-[#f0ece4]/80 print:text-black">
              <p className="font-semibold mb-1 text-[#2dd4bf] print:text-black">Verification {n}</p>
              <div className="grid grid-cols-3 gap-x-6 gap-y-1">
                <FormField label="Signed" />
                <FormField label="Place" />
                <FormField label="Date" />
              </div>
            </div>
          ))}

          <ExtensionBlock />
        </div>
      </main>
    </div>
  )
}

// ── Summary cards for Record of Equipment amendments ────────────────────────────

function RecordOfEquipmentE({ onBack }: { onBack: () => void }) {
  return (
    <SummaryView
      onBack={onBack}
      title="Record of Equipment — Form E"
      subtitle="Cargo Ship Safety — January 2026 Amendments"
      resolution="MSC.532(107)"
      items={[
        { change: 'Life-saving appliances, entries 9–9.2', detail: '"Number of immersion suits" replaces the previous entries 9, 9.1, and 9.2.' },
        { change: 'Navigational systems, new entry 16', detail: '"Electronic inclinometer" added after BNWAS (bridge navigational watch alarm system).' },
        { change: 'Ship type field', detail: '"Containership" added as a ship type option, per MSC.534(107).' },
      ]}
    />
  )
}

function RecordOfEquipmentP({ onBack }: { onBack: () => void }) {
  return (
    <SummaryView
      onBack={onBack}
      title="Record of Equipment — Form P"
      subtitle="Passenger Ship Safety — January 2026 Amendments"
      resolution="MSC.532(107)"
      items={[
        { change: 'Life-saving appliances, entries 10–10.2', detail: '"Number of immersion suits" replaces the previous entries 10, 10.1, and 10.2.' },
      ]}
    />
  )
}

function SummaryView({ onBack, title, subtitle, resolution, items }: {
  onBack: () => void
  title: string
  subtitle: string
  resolution: string
  items: { change: string; detail: string }[]
}) {
  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <CertFormHeader onBack={onBack} title={title} />

      <main className="flex-1 overflow-y-auto">
        <div className="cert-print-area max-w-2xl mx-auto px-6 py-8 print:bg-white print:text-black print:px-[20mm] print:py-[15mm]">
          <h2 className="font-display text-xl font-bold text-[#f0ece4] print:text-black tracking-wide mb-1">{title}</h2>
          <p className="font-mono text-sm text-[#2dd4bf] print:text-gray-700 mb-1">{subtitle}</p>
          <p className="font-mono text-xs text-[#6b7594] print:text-gray-500 mb-6">Resolution {resolution}</p>

          <div className="space-y-4 mb-8">
            {items.map((item, i) => (
              <div key={i} className="border-l-2 border-[#2dd4bf]/40 print:border-black/30 pl-4">
                <p className="font-mono text-sm font-semibold text-[#f0ece4] print:text-black">{item.change}</p>
                <p className="font-mono text-xs text-[#f0ece4]/70 print:text-gray-700 mt-1 leading-relaxed">{item.detail}</p>
              </div>
            ))}
          </div>

          <div className="rounded-lg border border-white/10 print:border-black/20 bg-[#111827] print:bg-gray-50 px-4 py-3">
            <p className="font-mono text-xs text-[#6b7594] print:text-gray-600 leading-relaxed">
              The full Record of Equipment forms are extensive tables best obtained from your flag state administration
              or the IMO. These summaries reflect only the January 2026 supplement amendments.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

// ── Certificate list page ───────────────────────────────────────────────────────

const FORM_MAP: Record<string, React.ComponentType<{ onBack: () => void }>> = {
  'cargo-safety-equipment': CargoShipSafetyForm,
  'cargo-safety-construction': ConstructionSafetyForm,
  'cargo-safety-radio': RadioSafetyForm,
  'isps-certificate': ISPSCertificateForm,
  'record-of-equipment-e': RecordOfEquipmentE,
  'record-of-equipment-p': RecordOfEquipmentP,
}

function CertificatesContent() {
  const router = useRouter()
  const [activeForm, setActiveForm] = useState<string | null>(null)

  if (activeForm) {
    const FormComponent = FORM_MAP[activeForm]
    if (FormComponent) return <FormComponent onBack={() => setActiveForm(null)} />
  }

  const formCerts = CERTIFICATES.filter(c => c.section === 'forms')
  const amendCerts = CERTIFICATES.filter(c => c.section === 'amendments')

  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <header className="flex-shrink-0 flex items-center justify-between gap-3 px-4 py-3
        bg-[#111827]/95 backdrop-blur-md border-b border-white/8">
        <div className="flex items-center gap-3">
          <button onClick={() => router.back()}
            className="w-9 h-9 flex items-center justify-center rounded-lg
              text-[#6b7594] hover:text-[#f0ece4] transition-colors"
            aria-label="Back">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
            Certificates
          </h1>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="px-4 py-5 flex flex-col gap-3 max-w-2xl mx-auto">
          <p className="font-mono text-xs text-[#6b7594] mb-2 leading-relaxed">
            SOLAS certificate form templates as amended through the January 2026 supplement.
            These are reference templates for the convention-mandated form structure.
          </p>

          {/* SOLAS Certificate Forms */}
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.2em] mt-2">
            SOLAS Certificate Forms
          </p>
          {formCerts.map(cert => (
            <CertCardButton key={cert.id} cert={cert} onClick={() => setActiveForm(cert.id)} />
          ))}

          {/* January 2026 Amendment Summaries */}
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.2em] mt-4">
            January 2026 Amendment Summaries
          </p>
          {amendCerts.map(cert => (
            <CertCardButton key={cert.id} cert={cert} onClick={() => setActiveForm(cert.id)} />
          ))}
        </div>
      </main>
    </div>
  )
}

function CertCardButton({ cert, onClick }: { cert: CertificateCard; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left bg-[#111827] border border-white/8
        hover:border-[#2dd4bf]/40 hover:bg-[#111827]/80
        rounded-xl px-5 py-4 transition-all duration-150"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="font-display text-base font-bold text-[#f0ece4] tracking-wide leading-snug">
            {cert.title}
          </p>
          <p className="font-mono text-xs text-[#2dd4bf] mt-1">{cert.subtitle}</p>
          <p className="font-mono text-xs text-[#f0ece4]/60 mt-2 leading-relaxed">{cert.description}</p>
        </div>
        <span className="flex-shrink-0 mt-1">
          {cert.type === 'full' ? (
            <span className="font-mono text-[10px] text-[#2dd4bf] border border-[#2dd4bf]/30 rounded px-1.5 py-0.5">
              FULL FORM
            </span>
          ) : (
            <span className="font-mono text-[10px] text-[#6b7594] border border-white/10 rounded px-1.5 py-0.5">
              SUMMARY
            </span>
          )}
        </span>
      </div>
    </button>
  )
}

export default function CertificatesPage() {
  return (
    <AuthGuard>
      <CertificatesContent />
    </AuthGuard>
  )
}
