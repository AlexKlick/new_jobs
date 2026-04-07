import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import type { EnrichedJob } from '../types';

interface QualityDashboardProps {
  jobs: EnrichedJob[];
}

export function QualityDashboard({ jobs }: QualityDashboardProps) {
  const { index } = useParams<{ index: string }>();
  const [selectedJobIndex, setSelectedJobIndex] = useState<number>(index ? parseInt(index, 10) : jobs[0]?.index || 1);

  useEffect(() => {
    if (index) {
      setSelectedJobIndex(parseInt(index, 10));
    }
  }, [index]);

  const selectedJob = jobs.find(j => j.index === selectedJobIndex);
  const jobsWithScores = jobs.filter(j => j.rubricScores);

  const avgScore = selectedJob?.rubricScores?.final
    ? Object.values(selectedJob.rubricScores.final).reduce((a, b) => a + b, 0) / Object.keys(selectedJob.rubricScores.final).length
    : null;

  return (
    <div className="quality-dashboard">
      <div className="quality-sidebar">
        <h3>Select Job</h3>
        <div className="quality-job-list">
          {jobsWithScores.map(job => {
            const jobAvg = job.rubricScores?.final
              ? Object.values(job.rubricScores.final).reduce((a, b) => a + b, 0) / Object.keys(job.rubricScores.final).length
              : null;
            return (
              <button
                key={job.index}
                className={`quality-job-item ${selectedJobIndex === job.index ? 'active' : ''}`}
                onClick={() => setSelectedJobIndex(job.index)}
              >
                <span className="quality-job-index">#{job.index}</span>
                <span className="quality-job-company">{job.company}</span>
                {jobAvg !== null && (
                  <span className={`quality-job-score ${jobAvg >= 4.5 ? 'high' : jobAvg >= 4.0 ? 'medium' : 'low'}`}>
                    {jobAvg.toFixed(1)}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="quality-main">
        {selectedJob ? (
          <>
            <div className="quality-header">
              <h2>{selectedJob.company} — {selectedJob.role}</h2>
              {selectedJob.evaluation && (
                <div className={`verdict-badge ${selectedJob.evaluation.verdict.toLowerCase()}`}>
                  {selectedJob.evaluation.verdict.replace('_', ' ')}
                </div>
              )}
            </div>

            {selectedJob.rubricScores && (
              <div className="quality-section">
                <h3>Rubric Scores</h3>
                {avgScore !== null && (
                  <div className="avg-score">
                    Average: <span className={`score ${avgScore >= 4.5 ? 'high' : avgScore >= 4.0 ? 'medium' : 'low'}`}>{avgScore.toFixed(2)}</span> / 5.0
                  </div>
                )}
                <div className="scores-grid">
                  {Object.entries(selectedJob.rubricScores.final).map(([key, value]) => (
                    <div key={key} className="score-item">
                      <div className="score-label">{key.replace(/_/g, ' ')}</div>
                      <div className="score-bar-container">
                        <div
                          className={`score-bar ${value >= 4.5 ? 'high' : value >= 4.0 ? 'medium' : 'low'}`}
                          style={{ width: `${(value / 5) * 100}%` }}
                        />
                      </div>
                      <div className="score-value">{value.toFixed(1)}</div>
                    </div>
                  ))}
                </div>

                {selectedJob.rubricScores.draft && (
                  <details className="draft-scores">
                    <summary>Show Draft Scores (for comparison)</summary>
                    <div className="scores-grid draft">
                      {Object.entries(selectedJob.rubricScores.draft).map(([key, value]) => (
                        <div key={key} className="score-item">
                          <div className="score-label">{key.replace(/_/g, ' ')}</div>
                          <div className="score-bar-container">
                            <div
                              className={`score-bar draft-bar ${value >= 4.5 ? 'high' : value >= 4.0 ? 'medium' : 'low'}`}
                              style={{ width: `${(value / 5) * 100}%` }}
                            />
                          </div>
                          <div className="score-value">{value.toFixed(1)}</div>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}

            {selectedJob.evaluation && (
              <div className="quality-section evaluation-section">
                <h3>External Evaluation</h3>

                <div className="eval-scores">
                  <h4>Evaluation Scores</h4>
                  <div className="scores-grid">
                    {Object.entries(selectedJob.evaluation.scores).map(([key, value]) => (
                      <div key={key} className="score-item">
                        <div className="score-label">{key.replace(/_/g, ' ')}</div>
                        <div className="score-bar-container">
                          <div
                            className={`score-bar eval-bar ${value >= 4 ? 'high' : value >= 3 ? 'medium' : 'low'}`}
                            style={{ width: `${(value / 5) * 100}%` }}
                          />
                        </div>
                        <div className="score-value">{value.toFixed(1)}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {selectedJob.evaluation.strengths.length > 0 && (
                  <div className="eval-strengths">
                    <h4>Strengths</h4>
                    <ul>
                      {selectedJob.evaluation.strengths.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {selectedJob.evaluation.weaknesses.length > 0 && (
                  <div className="eval-weaknesses">
                    <h4>Areas for Improvement</h4>
                    <ul>
                      {selectedJob.evaluation.weaknesses.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {selectedJob.evaluation.revision_suggestions.length > 0 && (
                  <div className="eval-suggestions">
                    <h4>Revision Suggestions</h4>
                    <ol>
                      {selectedJob.evaluation.revision_suggestions.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ol>
                  </div>
                )}

                <div className="human-review">
                  <h4>Human Review Checklist</h4>
                  <div className="checklist">
                    {selectedJob.evaluation.human_review_checklist.map((item, i) => (
                      <div key={i} className={`checklist-item ${item.status.toLowerCase()}`}>
                        <span className="check-icon">
                          {item.status === 'PASS' ? '✓' : item.status === 'FAIL' ? '✗' : '⚠'}
                        </span>
                        <span className="check-text">{item.item}</span>
                        {item.note && <span className="check-note">{item.note}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {!selectedJob.rubricScores && (
              <div className="no-quality-data">
                No quality data available for this job yet.
              </div>
            )}
          </>
        ) : (
          <div className="no-selection">Select a job to view quality analysis.</div>
        )}
      </div>
    </div>
  );
}
