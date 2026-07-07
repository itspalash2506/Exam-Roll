import { ArrowLeft, Palette } from 'lucide-react'
import StudentSummary from './StudentSummary.jsx'
import SubjectTable from './SubjectTable.jsx'
import Button from '../common/Button.jsx'

export default function ConfirmExtraction({ extractedData, fileCount = 1, onCustomize, onReupload }) {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm">
        <h3 className="mb-4 font-display text-h3 font-medium text-ink">Review Extracted Data</h3>
        <StudentSummary extractedData={extractedData} fileCount={fileCount} />
      </div>

      <SubjectTable extractedData={extractedData} />

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button variant="primary" size="lg" onClick={onCustomize} className="flex-1">
          <Palette size={16} />
          Customize &amp; Export
        </Button>
        <Button variant="ghost" size="lg" onClick={onReupload}>
          <ArrowLeft size={16} />
          Re-upload
        </Button>
      </div>
    </div>
  )
}
