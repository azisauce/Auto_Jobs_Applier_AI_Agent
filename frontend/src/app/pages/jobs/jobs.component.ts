import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../services/auth.service';
import { JobService, Job, JobListResponse } from '../../services/job.service';
import { ScriptService, ScriptStatusResponse } from '../../services/script.service';
import { Subscription } from 'rxjs';

@Component({
    selector: 'app-jobs',
    standalone: true,
    imports: [CommonModule, FormsModule],
    templateUrl: './jobs.component.html',
    styleUrl: './jobs.component.css'
})
export class JobsComponent implements OnInit, OnDestroy {
    jobs: Job[] = [];
    totalJobs = 0;
    currentPage = 1;
    totalPages = 1;
    limit = 20;
    sortBy = 'scraped_at';
    order = 'desc';
    loading = true;
    error = '';

    scriptStatus: ScriptStatusResponse | null = null;
    scriptLoading = false;
    showScriptMenu = false;

    username = '';
    private subs: Subscription[] = [];

    constructor(
        private jobService: JobService,
        private authService: AuthService,
        private scriptService: ScriptService
    ) { }

    ngOnInit(): void {
        this.subs.push(
            this.authService.username$.subscribe(u => this.username = u)
        );
        this.subs.push(
            this.scriptService.status$.subscribe(s => this.scriptStatus = s)
        );
        this.loadJobs();
        this.scriptService.getStatus().subscribe();
    }

    ngOnDestroy(): void {
        this.subs.forEach(s => s.unsubscribe());
    }

    loadJobs(): void {
        this.loading = true;
        this.error = '';
        this.jobService.getJobs(this.currentPage, this.limit, this.sortBy, this.order).subscribe({
            next: (res: JobListResponse) => {
                this.jobs = res.jobs;
                this.totalJobs = res.total;
                this.totalPages = res.pages;
                this.loading = false;
            },
            error: (err) => {
                this.error = err.error?.detail || 'Failed to load jobs';
                this.loading = false;
            }
        });
    }

    onSortChange(): void {
        this.currentPage = 1;
        this.loadJobs();
    }

    toggleOrder(): void {
        this.order = this.order === 'desc' ? 'asc' : 'desc';
        this.loadJobs();
    }

    prevPage(): void {
        if (this.currentPage > 1) {
            this.currentPage--;
            this.loadJobs();
        }
    }

    nextPage(): void {
        if (this.currentPage < this.totalPages) {
            this.currentPage++;
            this.loadJobs();
        }
    }

    openJob(link: string): void {
        window.open(link, '_blank', 'noopener,noreferrer');
    }

    runScript(type: 'collect' | 'score'): void {
        this.scriptLoading = true;
        this.showScriptMenu = false;
        this.scriptService.runScript(type).subscribe({
            next: () => {
                this.scriptLoading = false;
            },
            error: (err) => {
                this.scriptLoading = false;
                this.error = err.error?.detail || 'Failed to start script';
            }
        });
    }

    toggleScriptMenu(): void {
        this.showScriptMenu = !this.showScriptMenu;
    }

    logout(): void {
        this.authService.logout().subscribe();
    }

    getScoreClass(score: number | null): string {
        if (score === null || score === undefined) return 'score-none';
        if (score >= 80) return 'score-high';
        if (score >= 50) return 'score-mid';
        return 'score-low';
    }

    getScoreLabel(score: number | null): string {
        if (score === null || score === undefined) return '—';
        return score.toString();
    }

    formatDate(dateStr: string): string {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }
}
