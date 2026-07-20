import React, { useState } from 'react';
import { 
  ShieldCheck, Table, Layout, Search, Stethoscope, 
  Pill, HeartPulse, Activity, Glasses, Ear, 
  Zap, Info, CheckCircle2, XCircle, ChevronRight
} from 'lucide-react';

const MOCK_DRUG_DB = [
  { name: 'Lisinopril', tier: 'Tier 1: Preferred Generic', cost: '$0 copay' },
  { name: 'Atorvastatin', tier: 'Tier 1: Preferred Generic', cost: '$0 copay' },
  { name: 'Cyanocobalamin', tier: 'Tier 2: Generic (Additional)', cost: '$5 copay' },
  { name: 'Eliquis', tier: 'Tier 3: Preferred Brand', cost: '18% coinsurance' },
  { name: 'Insulin Glargine', tier: 'Covered Insulin', cost: '18% (Max $35)' },
  { name: 'Contour Next Monitor', tier: 'Diabetes Supplies', cost: '$0 copay' },
  { name: 'Accu-Chek Guide', tier: 'Diabetes Supplies', cost: '$0 copay' },
];

export default function PlanDetailsMockup() {
  const [isProView, setIsProView] = useState(false);
  const [network, setNetwork] = useState('in'); // 'in' or 'out'
  const [searchQuery, setSearchQuery] = useState('');

  // Derived state for drug search
  const filteredDrugs = searchQuery 
    ? MOCK_DRUG_DB.filter(d => d.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900 selection:bg-blue-100">
      
      {/* Top Navigation & Controls */}
      <header className="sticky top-0 z-50 bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-blue-600" />
            <h1 className="font-bold text-lg hidden sm:block text-slate-800">
              AARP® Medicare Advantage from UHC <span className="font-normal text-slate-500">NC-0015 (HMO-POS)</span>
            </h1>
            <h1 className="font-bold text-lg sm:hidden text-slate-800">UHC NC-0015</h1>
          </div>

          <div className="flex items-center gap-4">
            {/* Pro View Toggle */}
            <div className="flex items-center gap-2 bg-slate-100 p-1 rounded-lg border border-slate-200">
              <button 
                onClick={() => setIsProView(false)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-all ${!isProView ? 'bg-white shadow-sm text-blue-600' : 'text-slate-500 hover:text-slate-700'}`}
              >
                <Layout className="w-4 h-4" />
                <span className="hidden sm:inline">Consumer</span>
              </button>
              <button 
                onClick={() => setIsProView(true)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-all ${isProView ? 'bg-white shadow-sm text-blue-600' : 'text-slate-500 hover:text-slate-700'}`}
              >
                <Table className="w-4 h-4" />
                <span className="hidden sm:inline">Pro View</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        
        {}
        {/* Universal At a Glance Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end mb-6 gap-4">
            <div>
              <h2 className="text-3xl font-extrabold text-slate-900 tracking-tight">2026 Summary of Benefits</h2>
              <p className="text-slate-500 mt-1">Plan ID: H5253-117-000</p>
            </div>
            
            {/* Global Network Toggle */}
            <div className="inline-flex items-center bg-blue-50 p-1.5 rounded-full border border-blue-100 shadow-inner">
              <button 
                onClick={() => setNetwork('in')}
                className={`px-6 py-2 rounded-full text-sm font-semibold transition-all ${network === 'in' ? 'bg-blue-600 text-white shadow-md' : 'text-blue-700 hover:bg-blue-100'}`}
              >
                In-Network
              </button>
              <button 
                onClick={() => setNetwork('out')}
                className={`px-6 py-2 rounded-full text-sm font-semibold transition-all ${network === 'out' ? 'bg-slate-700 text-white shadow-md' : 'text-blue-700 hover:bg-blue-100'}`}
              >
                Out-of-Network
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Premium Card */}
            <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm flex flex-col justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Monthly Premium</p>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-4xl font-extrabold text-slate-900">$0</span>
                </div>
              </div>
              <div className="mt-4 bg-slate-50 border border-slate-100 p-3 rounded-lg flex items-start gap-2">
                <Info className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" />
                <p className="text-xs text-slate-600 leading-relaxed">
                  <strong>Transparency Note:</strong> You must continue to pay your Medicare Part B premium (standard rate of <strong>$202.90</strong>/mo for 2026).
                </p>
              </div>
            </div>

            {/* MOOP Card */}
            <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm flex flex-col justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Max Out-of-Pocket</p>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-4xl font-extrabold text-slate-900">
                    {network === 'in' ? '$4,200' : 'Combined*'}
                  </span>
                  <span className="text-sm font-medium text-slate-500">/ year</span>
                </div>
              </div>
              <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
                <ShieldCheck className="w-4 h-4 text-emerald-500" />
                <span>Does not include prescription drugs.</span>
              </div>
            </div>

            {/* Highlighted Benefits */}
            <div className="bg-gradient-to-br from-blue-600 to-indigo-700 rounded-2xl p-6 text-white shadow-md flex flex-col justify-between">
              <div>
                <p className="text-sm font-semibold text-blue-200 uppercase tracking-wider mb-3">Top Extra Benefits</p>
                <ul className="space-y-3">
                  <li className="flex items-center gap-3">
                    <div className="bg-white/20 p-1.5 rounded-md"><Zap className="w-4 h-4 text-yellow-300" /></div>
                    <span className="font-medium">$45 / quarter OTC Credit</span>
                  </li>
                  <li className="flex items-center gap-3">
                    <div className="bg-white/20 p-1.5 rounded-md"><Stethoscope className="w-4 h-4 text-blue-100" /></div>
                    <span className="font-medium">$2,000 Dental Allowance</span>
                  </li>
                  <li className="flex items-center gap-3">
                    <div className="bg-white/20 p-1.5 rounded-md"><Glasses className="w-4 h-4 text-blue-100" /></div>
                    <span className="font-medium">$200 Eyewear Allowance</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        {}
        {!isProView ? (
          <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            
            {/* MEDICAL BENEFITS SECTION */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <HeartPulse className="w-6 h-6 text-rose-500" />
                <h3 className="text-xl font-bold text-slate-900">Medical Care</h3>
              </div>
              <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                
                {/* Doctor Visits */}
                <div className="p-6 border-b border-slate-100 grid md:grid-cols-2 gap-6">
                  <div>
                    <h4 className="font-semibold text-slate-800 mb-4">Doctor Visits</h4>
                    <div className="space-y-4">
                      <div className="flex justify-between items-center p-3 bg-slate-50 rounded-lg">
                        <span className="text-slate-600">Primary Care (PCP)</span>
                        <span className={`font-bold ${network === 'in' ? 'text-slate-900' : 'text-red-500'}`}>
                          {network === 'in' ? '$0 copay' : 'Not covered'}
                        </span>
                      </div>
                      <div className="flex justify-between items-center p-3 bg-slate-50 rounded-lg">
                        <span className="text-slate-600">Specialist</span>
                        <span className={`font-bold ${network === 'in' ? 'text-slate-900' : 'text-red-500'}`}>
                          {network === 'in' ? '$35 copay' : 'Not covered'}
                        </span>
                      </div>
                      <div className="flex justify-between items-center p-3 bg-slate-50 rounded-lg">
                        <span className="text-slate-600">Virtual Medical Visit</span>
                        <span className={`font-bold text-slate-900`}>$0 copay</span>
                      </div>
                    </div>
                  </div>

                  {/* Visual Hospitalization Timeline */}
                  <div>
                    <h4 className="font-semibold text-slate-800 mb-4">Inpatient Hospital Care</h4>
                    {network === 'in' || network === 'out' ? (
                      <div className="space-y-3">
                        <p className="text-sm text-slate-500">Your daily costs for a single hospital stay:</p>
                        <div className="flex h-12 w-full rounded-lg overflow-hidden border border-slate-200">
                          <div className="w-3/5 bg-rose-100 flex flex-col justify-center items-center border-r border-rose-200 relative group cursor-help">
                            <span className="text-xs font-bold text-rose-700">Days 1-6</span>
                            <span className="text-sm font-black text-rose-900">$455/day</span>
                          </div>
                          <div className="w-2/5 bg-emerald-100 flex flex-col justify-center items-center relative group cursor-help">
                            <span className="text-xs font-bold text-emerald-700">Days 7+</span>
                            <span className="text-sm font-black text-emerald-900">$0/day</span>
                          </div>
                        </div>
                        <p className="text-xs text-slate-400 mt-2 italic">*Unlimited days covered. {network === 'out' ? 'CaroMont providers in Gaston County only.' : ''}</p>
                      </div>
                    ) : null}
                  </div>
                </div>

                {/* Testing & Imaging */}
                <div className="p-6 bg-slate-50/50">
                  <h4 className="font-semibold text-slate-800 mb-4">Testing & Imaging</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-white p-4 rounded-xl border border-slate-100 shadow-sm text-center">
                      <p className="text-xs text-slate-500 mb-1">Lab Services</p>
                      <p className={`font-bold ${network === 'in' ? 'text-slate-900' : 'text-red-500'}`}>
                        {network === 'in' ? '$0 copay' : 'Not covered'}
                      </p>
                    </div>
                    <div className="bg-white p-4 rounded-xl border border-slate-100 shadow-sm text-center">
                      <p className="text-xs text-slate-500 mb-1">X-Rays</p>
                      <p className={`font-bold ${network === 'in' ? 'text-slate-900' : 'text-red-500'}`}>
                        {network === 'in' ? '$30 copay' : 'Not covered'}
                      </p>
                    </div>
                    <div className="bg-white p-4 rounded-xl border border-slate-100 shadow-sm text-center">
                      <p className="text-xs text-slate-500 mb-1">MRI / CT Scan</p>
                      <p className={`font-bold ${network === 'in' ? 'text-slate-900' : 'text-red-500'}`}>
                        {network === 'in' ? '$260 copay' : 'Not covered'}
                      </p>
                    </div>
                    <div className="bg-white p-4 rounded-xl border border-slate-100 shadow-sm text-center">
                      <p className="text-xs text-slate-500 mb-1">Diagnostic Tests</p>
                      <p className={`font-bold ${network === 'in' ? 'text-slate-900' : 'text-red-500'}`}>
                        {network === 'in' ? '$50 copay' : 'Not covered'}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            {}
            <section>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Pill className="w-6 h-6 text-indigo-500" />
                  <h3 className="text-xl font-bold text-slate-900">Prescription Drugs (Part D)</h3>
                </div>
              </div>

              <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
                
                {/* Interactive Search Tool */}
                <div className="bg-indigo-50 p-4 rounded-xl border border-indigo-100 mb-8">
                  <div className="flex flex-col sm:flex-row gap-4 items-center">
                    <div className="flex-1 w-full">
                      <label className="block text-sm font-semibold text-indigo-900 mb-2">Check Coverage & Tier (Interactive Demo)</label>
                      <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-indigo-300" />
                        <input 
                          type="text" 
                          placeholder="Try typing 'Lisinopril', 'Insulin', or 'Contour'..." 
                          className="w-full pl-10 pr-4 py-3 rounded-lg border-none ring-1 ring-indigo-200 focus:ring-2 focus:ring-indigo-500 shadow-sm text-slate-800"
                          value={searchQuery}
                          onChange={(e) => setSearchQuery(e.target.value)}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Search Results Dropdown */}
                  {searchQuery && (
                    <div className="mt-4 space-y-2">
                      {filteredDrugs.length > 0 ? (
                        filteredDrugs.map((drug, i) => (
                          <div key={i} className="flex items-center justify-between bg-white p-3 rounded-lg shadow-sm border border-indigo-100">
                            <div>
                              <p className="font-bold text-slate-800">{drug.name}</p>
                              <p className="text-xs text-slate-500">{drug.tier}</p>
                            </div>
                            <div className="bg-indigo-100 px-3 py-1 rounded-full">
                              <span className="font-bold text-indigo-800">{drug.cost}</span>
                            </div>
                          </div>
                        ))
                      ) : (
                        <p className="text-sm text-indigo-600 italic px-2">No matching mock data. Check formulary.</p>
                      )}
                    </div>
                  )}
                </div>

                {/* Tiers display */}
                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {[
                    { tier: 'Tier 1: Pref Generic', cost: '$0', ded: 'No deductible' },
                    { tier: 'Tier 2: Generic', cost: '$5', ded: 'No deductible' },
                    { tier: 'Tier 3: Pref Brand', cost: '18%', ded: 'Subject to $440 ded.' },
                    { tier: 'Covered Insulin', cost: '18%', sub: 'Max $35', ded: 'No deductible applies' },
                    { tier: 'Tier 4: Non-Pref', cost: '42%', ded: 'Subject to $440 ded.' },
                    { tier: 'Tier 5: Specialty', cost: '28%', ded: 'Subject to $440 ded.' },
                  ].map((t, idx) => (
                    <div key={idx} className="border border-slate-100 rounded-xl p-4 bg-slate-50 flex justify-between items-center">
                      <div>
                        <p className="font-semibold text-slate-800 text-sm">{t.tier}</p>
                        <p className="text-xs text-slate-500 mt-0.5">{t.ded}</p>
                      </div>
                      <div className="text-right">
                        <span className="text-lg font-extrabold text-slate-900">{t.cost}</span>
                        {t.sub && <p className="text-xs font-bold text-emerald-600">{t.sub}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            {}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Activity className="w-6 h-6 text-emerald-500" />
                <h3 className="text-xl font-bold text-slate-900">Extra Benefits</h3>
              </div>
              
              <div className="grid md:grid-cols-2 gap-4">
                <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex gap-4 items-start">
                  <div className="bg-slate-100 p-2.5 rounded-xl text-slate-600">
                    <Stethoscope className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-900 mb-1">Routine Dental</h4>
                    <p className="text-slate-600 text-sm leading-relaxed mb-3">
                      <strong>$2,000 allowance</strong> per year for covered services. Freedom to see any dentist.
                    </p>
                    <div className="text-sm bg-slate-50 rounded-lg p-2 space-y-1">
                      <div className="flex justify-between"><span>Preventive (Exams, X-rays):</span> <strong>$0 copay</strong></div>
                      <div className="flex justify-between"><span>Comprehensive (Crowns, etc):</span> <strong>50% coinsurance</strong></div>
                    </div>
                  </div>
                </div>

                <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex gap-4 items-start">
                  <div className="bg-slate-100 p-2.5 rounded-xl text-slate-600">
                    <Glasses className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-900 mb-1">Routine Vision</h4>
                    <p className="text-slate-600 text-sm leading-relaxed mb-3">
                      <strong>$200 allowance</strong> every 2 years for frames/contacts. Includes free standard lenses.
                    </p>
                    <div className="text-sm bg-slate-50 rounded-lg p-2 space-y-1">
                      <div className="flex justify-between"><span>Routine Eye Exam:</span> 
                        <strong className={network === 'out' ? 'text-red-500' : ''}>
                          {network === 'in' ? '$0 copay' : 'Not covered'}
                        </strong>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex gap-4 items-start">
                  <div className="bg-slate-100 p-2.5 rounded-xl text-slate-600">
                    <Ear className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-900 mb-1">Hearing Services</h4>
                    <p className="text-slate-600 text-sm leading-relaxed mb-3">
                      Up to 2 hearing aids per year through UnitedHealthcare Hearing.
                    </p>
                    <div className="text-sm bg-slate-50 rounded-lg p-2 space-y-1">
                      <div className="flex justify-between"><span>Routine Exam:</span> 
                        <strong className={network === 'out' ? 'text-red-500' : ''}>
                          {network === 'in' ? '$0 copay' : 'Not covered'}
                        </strong>
                      </div>
                      <div className="flex justify-between"><span>Prescription Aids:</span> <strong>$199 - $1,249 copay</strong></div>
                      <div className="flex justify-between"><span>OTC Aids:</span> <strong>$199 - $829 copay</strong></div>
                    </div>
                  </div>
                </div>

                <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex gap-4 items-start">
                  <div className="bg-emerald-100 p-2.5 rounded-xl text-emerald-600">
                    <Zap className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-900 mb-1">Over-the-Counter (OTC)</h4>
                    <p className="text-slate-600 text-sm leading-relaxed mb-2">
                      <strong>$45 credit every quarter</strong> to spend in-store or online on vitamins, pain relievers, first aid, and more.
                    </p>
                    <div className="inline-flex items-center text-xs font-medium text-emerald-700 bg-emerald-50 px-2 py-1 rounded">
                      Use at Walmart, Walgreens, Dollar General
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        ) : (
          
          <div className="animate-in fade-in slide-in-from-top-4 duration-500">
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
              <table className="min-w-full text-sm text-left">
                <thead className="bg-slate-800 text-slate-50 font-medium">
                  <tr>
                    <th className="px-4 py-3 rounded-tl-xl">Benefit Category</th>
                    <th className="px-4 py-3 border-l border-slate-600 bg-blue-900/50">In-Network Cost</th>
                    <th className="px-4 py-3 border-l border-slate-600 rounded-tr-xl">Out-of-Network Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Primary Care Provider (PCP)</td>
                    <td className="px-4 py-3 border-l border-slate-100 bg-blue-50/30 font-medium">$0 copay</td>
                    <td className="px-4 py-3 border-l border-slate-100 text-red-600">Not covered</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Specialist Visit</td>
                    <td className="px-4 py-3 border-l border-slate-100 bg-blue-50/30 font-medium">$35 copay</td>
                    <td className="px-4 py-3 border-l border-slate-100 text-red-600">Not covered</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Preventive Care (Medicare-covered)</td>
                    <td className="px-4 py-3 border-l border-slate-100 bg-blue-50/30 font-medium">$0 copay</td>
                    <td className="px-4 py-3 border-l border-slate-100 text-slate-500 text-xs">Flu/Covid: $0. Other: Not Covered</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Inpatient Hospital Care</td>
                    <td className="px-4 py-3 border-l border-slate-100 bg-blue-50/30 font-medium">$455/day (Days 1-6)<br/>$0/day (Days 7+)</td>
                    <td className="px-4 py-3 border-l border-slate-100 font-medium">$455/day (Days 1-6)<br/>$0/day (Days 7+)* CaroMont only</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Outpatient Surgery / ASC</td>
                    <td className="px-4 py-3 border-l border-slate-100 bg-blue-50/30 font-medium">$0 Colonoscopy / $325 ASC / $455 Hosp</td>
                    <td className="px-4 py-3 border-l border-slate-100 text-red-600">Not covered</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Emergency Care</td>
                    <td colSpan={2} className="px-4 py-3 border-l border-slate-100 font-medium text-center bg-slate-50">
                      $150 copay (Combined In/Out of Network. $0 outside US)
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Diagnostic Radiology (MRI/CT)</td>
                    <td className="px-4 py-3 border-l border-slate-100 bg-blue-50/30 font-medium">$0 mammogram / $260 other</td>
                    <td className="px-4 py-3 border-l border-slate-100 text-red-600">Not covered</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Routine Dental</td>
                    <td colSpan={2} className="px-4 py-3 border-l border-slate-100 font-medium text-center bg-slate-50">
                      $2,000 allowance. Prev: $0 copay. Comp: 50% coinsurance.
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold">Prescription Drugs (Part D)</td>
                    <td colSpan={2} className="px-4 py-3 border-l border-slate-100 text-xs">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-left">
                        <div><strong>Tier 1:</strong> $0</div>
                        <div><strong>Tier 2:</strong> $5</div>
                        <div><strong>Tier 3:</strong> 18% (Ded: $440)</div>
                        <div><strong>Insulin:</strong> 18% (Max $35)</div>
                        <div><strong>Tier 4:</strong> 42% (Ded: $440)</div>
                        <div><strong>Tier 5:</strong> 28% (Ded: $440)</div>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-500 mt-3 text-right">Pro View active: Condensed formatting for rapid scanning.</p>
          </div>
        )}
      </main>
    </div>
  );
}