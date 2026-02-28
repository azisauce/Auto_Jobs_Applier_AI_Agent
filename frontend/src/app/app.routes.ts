import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';

export const routes: Routes = [
    {
        path: 'login',
        loadComponent: () => import('./pages/login/login.component').then(m => m.LoginComponent),
    },
    {
        path: 'jobs',
        loadComponent: () => import('./pages/jobs/jobs.component').then(m => m.JobsComponent),
        canActivate: [authGuard],
    },
    {
        path: '',
        redirectTo: '/jobs',
        pathMatch: 'full',
    },
    {
        path: '**',
        redirectTo: '/jobs',
    },
];
