import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Job {
    id: number;
    linkedin_job_id: string;
    title: string;
    company: string;
    location: string;
    link: string;
    apply_method: string;
    description: string;
    score: number | null;
    score_breakdown: string | null;
    has_connections: boolean;
    connection_count: number;
    scraped_at: string;
    scored_at: string | null;
}

export interface JobListResponse {
    jobs: Job[];
    total: number;
    page: number;
    limit: number;
    pages: number;
}

export interface JobFilters {
    status?: 'viewed' | 'not_viewed' | 'all';
    location?: string;
    title?: string;
    company?: string;
}

@Injectable({ providedIn: 'root' })
export class JobService {
    private apiUrl = '/api/jobs';

    constructor(private http: HttpClient) { }

    getJobs(
        page: number = 1,
        limit: number = 20,
        sortBy: string = 'scraped_at',
        order: string = 'desc',
        filters: JobFilters = {}
    ): Observable<JobListResponse> {
        let params = new HttpParams()
            .set('page', page.toString())
            .set('limit', limit.toString())
            .set('sort_by', sortBy)
            .set('order', order);

        if (filters.status && filters.status !== 'all') {
            params = params.set('status', filters.status);
        }
        if (filters.location?.trim()) {
            params = params.set('location', filters.location.trim());
        }
        if (filters.title?.trim()) {
            params = params.set('title', filters.title.trim());
        }
        if (filters.company?.trim()) {
            params = params.set('company', filters.company.trim());
        }

        return this.http.get<JobListResponse>(this.apiUrl, { params });
    }

    getJob(id: number): Observable<Job> {
        return this.http.get<Job>(`${this.apiUrl}/${id}`);
    }
}
