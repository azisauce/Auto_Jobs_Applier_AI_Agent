import { Component, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
    selector: 'app-login',
    standalone: true,
    imports: [CommonModule, FormsModule],
    templateUrl: './login.component.html',
    styleUrl: './login.component.css'
})
export class LoginComponent {
    username = '';
    password = '';
    error = '';
    loading = false;

    constructor(
        private authService: AuthService,
        private router: Router,
        private cdr: ChangeDetectorRef
    ) { }

    onSubmit(): void {
        if (!this.username || !this.password) {
            this.error = 'Please enter both username and password';
            return;
        }

        this.loading = true;
        this.error = '';
        this.cdr.detectChanges();

        this.authService.login(this.username, this.password).subscribe({
            next: () => {
                this.loading = false;
                this.cdr.detectChanges();
                this.router.navigate(['/jobs']);
            },
            error: (err) => {
                this.loading = false;
                this.error = err.error?.detail || 'Login failed. Please try again.';
                this.cdr.detectChanges();
            }
        });
    }
}
